
#Copyright (c) 2024 Vanderbilt University  
#Authors: Jules White, Allen Karns, Karely Rodriguez, Max Moundas

# set up retriever function that accepts a a query, user, and/or list of keys for where claus

import os

import psycopg2
from pgvector.psycopg2 import register_vector
from common.credentials import get_credentials
from common.validate import validated
from shared_functions import generate_embeddings
import logging
import boto3
from boto3.dynamodb.conditions import Key

# Configure Logging 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('embedding_dual_retrieval')

pg_host = os.environ['RAG_POSTGRES_DB_READ_ENDPOINT']
pg_user = os.environ['RAG_POSTGRES_DB_USERNAME']
pg_database = os.environ['RAG_POSTGRES_DB_NAME']
rag_pg_password = os.environ['RAG_POSTGRES_DB_SECRET']
embedding_provider = os.environ['EMBEDDING_PROVIDER']
qa_model_name = os.environ['QA_MODEL_NAME']
api_version = os.environ['API_VERSION']
object_access_table = os.environ['OBJECT_ACCESS_TABLE']


pg_password = get_credentials(rag_pg_password)

def get_top_similar_qas(query_embedding, src_ids, limit=5):
    with psycopg2.connect(
        host=pg_host,
        database=pg_database,
        user=pg_user,
        password=pg_password,
        port=3306
    ) as conn:
        
        # Register pgvector extension
        register_vector(conn)
        with conn.cursor() as cur:

            # Ensure the query_embedding is a list of floats
            assert isinstance(query_embedding, list), "Expected query_embedding to be a list of floats"
            #print(f"here is the query embedding {query_embedding}")

            # Convert the query_embedding list to a PostgreSQL array literal
            embedding_literal = "[" + ",".join(map(str, query_embedding)) + "]"

            # Prepare SQL query and parameters based on whether src_ids are provided
            query_params = [embedding_literal, limit]  # query_embedding is already a list of floats
            src_clause = ""

            if src_ids:
                # Convert src_ids list to a format suitable for the ANY clause in PostgreSQL
                src_ids_array = "{" + ",".join(map(str, src_ids)) + "}"
            
                

            query_params.insert(1, src_ids_array)  # Append the limit to the query parameters
             # Append the limit to the query parameters

            # Create SQL query string with a placeholder for the optional src_clause and a limit
            sql_query = f"""
                SELECT content, src, locations, orig_indexes, char_index, token_count, id, ((qa_vector_embedding <#> %s::vector) * -1) AS distance
                FROM embeddings 
                WHERE src = ANY(%s)  -- Use the ARRAY constructor for src_ids
                ORDER BY distance DESC  -- Order by distance for ordering  
                LIMIT %s  -- Use a placeholder for the limit
            """
            logger.info(f"Executing QA SQL query: {sql_query}")
            try:
                cur.execute(sql_query, query_params)
                top_docs = cur.fetchall()
                logger.info(f"Top QA docs retrieved: {top_docs}")
            except Exception as e:
                logger.error(f"An error occurred while fetching top similar QAs: {e}", exc_info=True)
                raise
    return top_docs


def get_top_similar_docs(query_embedding, src_ids, limit=5):
    with psycopg2.connect(
        host=pg_host,
        database=pg_database,
        user=pg_user,
        password=pg_password,
        port=3306
    ) as conn:
        
        # Register pgvector extension
        register_vector(conn)
        with conn.cursor() as cur:
            
            # Ensure the query_embedding is a list of floats
            assert isinstance(query_embedding, list), "Expected query_embedding to be a list of floats"

            if src_ids:
                # Convert src_ids list to a format suitable for the ANY clause in PostgreSQL
                src_ids_array = "{" + ",".join(map(str, src_ids)) + "}"

            # Prepare the query parameters
            # Note: query_embedding is passed directly as a list of floats
            query_params = [query_embedding, src_ids_array, limit]  # src_ids should be a tuple for psycopg2 to convert it to an array

            # Create SQL query string with placeholders for parameters
            sql_query = """
                SELECT content, src, locations, orig_indexes, char_index, token_count, id, ((vector_embedding <#> %s::vector) * -1) AS distance
                FROM embeddings 
                WHERE src = ANY(%s)  -- Use the ARRAY constructor for src_ids
                ORDER BY distance DESC  -- Order by distance for ordering  
                LIMIT %s  -- Use a placeholder for the limit
            """
            logger.info(f"Executing Top Similar SQL query: {sql_query}")
            try:
                cur.execute(sql_query, query_params)
                top_docs = cur.fetchall()
                logger.info(f"Top similar docs retrieved: {top_docs}")
            except Exception as e:
                logger.error(f"An error occurred while fetching top similar docs: {e}", exc_info=True)
                raise
    return top_docs

    


def classify_src_ids_by_access(raw_src_ids, current_user):
    accessible_src_ids = []
    access_denied_src_ids = []

    # Define the permission levels that grant access
    permission_levels = ['read', 'write', 'owner']

    # Initialize a DynamoDB resource using boto3
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(object_access_table)

    try:
        # Iterate over each src_id and perform a query
        for src_id in raw_src_ids:
            response = table.query(
                KeyConditionExpression=Key('object_id').eq(src_id) & Key('principal_id').eq(current_user)
            )

            # Check if the response has any items with the required permission levels
            items_with_access = [item for item in response.get('Items', []) if item['permission_level'] in permission_levels]

            # Classify the src_id based on whether it has accessible items
            if items_with_access:
                accessible_src_ids.append(src_id)
            else:
                access_denied_src_ids.append(src_id)
        logger.info(f"Accessible src_ids: {accessible_src_ids}, Access denied src_ids: {access_denied_src_ids}")        

    except Exception as e:
        logging.error(f"An error occurred while classifying src_ids by access: {e}")
        # Depending on the use case, you may want to handle the error differently
        # Here we're considering all src_ids as denied if there's an error
        access_denied_src_ids.extend(raw_src_ids)
    print(f"Accessible src_ids: {accessible_src_ids}, Access denied src_ids: {access_denied_src_ids}")
    return accessible_src_ids, access_denied_src_ids

 
@validated("dual-retrieval")
def process_input_with_dual_retrieval(event, context, current_user, name, data):
    data = data['data']
    content = data['userInput']
    raw_src_ids = data['dataSources']
    limit = data['limit']

    accessible_src_ids, access_denied_src_ids = classify_src_ids_by_access(raw_src_ids, current_user)
    src_ids = accessible_src_ids

    embedding_result = generate_embeddings(content, embedding_provider)
    if embedding_result["success"]:
        embeddings = embedding_result["data"]
        content_vector_token_count = embedding_result["token_count"]
        print(f"Vector Token Count: {content_vector_token_count}")
    else:
        raise Exception(embedding_result["error"])
    
    # Step 1: Get documents related to the user input from the database
    related_docs = get_top_similar_docs(embeddings, src_ids, limit)
    
    
    related_qas = get_top_similar_qas(embeddings, src_ids, limit)
    related_docs.extend(related_qas)

    print(f"Here are the related docs {related_docs}")

    return {"result":related_docs}
    


   






