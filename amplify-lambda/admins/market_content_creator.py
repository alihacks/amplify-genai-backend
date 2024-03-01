from openai import OpenAI
import yaml
import argparse
import boto3
import os
import re
import concurrent.futures

MARKET_CATEGORIES_DYNAMO_TABLE='amplify-support-dev-market-categories'

parser = argparse.ArgumentParser(description='Load a YAML taxonomy into a database.')
parser.add_argument('filename', type=str, help='The YAML file containing the taxonomy.')
parser.add_argument('profile', type=str, help='The AWS profile to use.')
args = parser.parse_args()

print(f"Using profile {args.profile}")
boto3.setup_default_session(profile_name="vandy-amplify")

def get_secret_value(secret_name):
    # Create a Secrets Manager client
    client = boto3.client('secretsmanager')

    try:
        # Retrieve the secret value
        response = client.get_secret_value(SecretId=secret_name)
        secret_value = response['SecretString']
        return secret_value

    except Exception as e:
        raise ValueError(f"Failed to retrieve secret '{secret_name}': {str(e)}")

def get_openai_client():
    openai_api_key = get_secret_value("OPENAI_API_KEY")
    client = OpenAI(
        api_key=openai_api_key
    )
    return client

def prompt_llm(client, system, user):
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]

    result = ""
    response = client.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=messages
    )

    return response.choices[0].message.content


prompt_idea_system_prompt_v1 = """
These are the bounds that we are going to place on how we use ChatGPT in the workplace: We are going to use the following framework in exploring how to use Generative AI to aid people: 1. Better decision making by having the LLM give them multiple possible approaches to solving a problem, multiple potential interpretations of data, identifying assumptions in their decisions and helping them evaluate the validity of those assumptions, often by challenging them. 2. Coming up with innovative ideas by serving as a brainstorming partner that offers lots of different and diverse options for any task. 3. Simultaneously applying multiple structured approaches to representing and solving problems. 4. Allowing people to iterate faster and spend more time exploring possibilities by creating initial drafts that are good starting points. 5. Aiding in summarization, drafting of plans, identification of supporting quotations or evidence, identification of assumptions, in 3-5 pages of text. Provide one approach to using ChatGPT to perform the following and one specific prompt that would be used for this. Make sure and include placeholders like <INSERT TEXT> (insert actual newlines) if the prompt relies on outside information, etc. If the prompt relies on a lot of information (e.g., more than a sentence or two), separate it like this:
----------------
<INSERT TEXT>
----------------
Be thoughtful and detailed in creating a really useful prompt that can be reused and are very detailed.

Output the prompt in a ```template code block.
"""

def extract_prompt_template(prompt):
    pattern = r"```template\s*\n(.*?)```"
    matches = re.findall(pattern, prompt, re.DOTALL)
    if matches:
        return matches[0]
    else:
        return None

def generate_prompt_idea(client, task):
    system = """
        These are the bounds that we are going to place on how we use ChatGPT in the workplace: 
        We are going to use the following framework in exploring how to use Generative AI to aid people: 
        1. Better decision making by having the LLM give them multiple possible approaches to solving a problem, 
          multiple potential interpretations of data, identifying assumptions in their decisions and helping them 
          evaluate the validity of those assumptions, often by challenging them. 
        2. Coming up with innovative ideas by serving as a brainstorming partner that offers lots of different 
           and diverse options for any task. 
        3. Simultaneously applying multiple structured approaches to representing and solving problems. 
        4. Allowing people to iterate faster and spend more time exploring possibilities by creating initial 
           drafts that are good starting points.
        5. Aiding in summarization, drafting of plans, identification of supporting quotations or evidence, 
           identification of assumptions, in 3-5 pages of text. Provide one approach to using ChatGPT to perform 
           the following and one specific prompt that would be used for this. 
           
        Make sure and include placeholders like <INSERT TEXT> (insert actual newlines) if the prompt relies on 
        outside information, etc. If the prompt relies on a lot of information (e.g., more than a sentence or two), 
        separate it like this:
----------------
<INSERT TEXT>
----------------
        Be thoughtful and detailed in creating a really useful prompt that can be reused and are very detailed. 
        Do not suggest anything that requires current knowledge, such as recent news or articles, non-historical 
        people, references to specific papers or cases, specific numbers that you the LLM won't have access to, etc.

        Output the prompt in a ```template code block.
"""

    user = f"""The task is: {task}

```template

"""
    return prompt_llm(client, system, user)


def assign_roles_to_prompt_inputs(client, prompt):
    system = """
        The prompt template below contains <PLACEHOLDERS>. 
        The user provides some information and the LLM infers other information from what the user provided.
        We want the LLM to infer as much information as possible. We want the user to provide at most 2-4 pieces of information.
        If absolutely necessary, you can have the user provide more information, but try to keep it to 2-4 pieces of information.
        Think carefully, which of the placeholders are information that the user needs to fill in that
        there is no possible way the LLM could infer from the values that are provided earlier by the user?
        Which of the placeholders are information that the LLM could infer from the values that are 
        provided earlier by the user? For the information that the user ABSOLUTELY MUST fill in, update 
        the placeholder to <USER: PLACEHOLDER>. If the LLM can infer it, update the placeholder 
        to <LLM: PLACEHOLDER>. To make the template useful, only require the user to fill in 
        information that is essential and let the LLM infer as much as possible. 
        HAVE THE LLM INFER AS MUCH AS POSSIBLE. 
        
        YOU CAN USE A MAXIMUM OF THREE <USER: PLACEHOLDER>. If you need more than THREE <USER: PLACEHOLDER>s, you 
        should just include a section where the user can provide whatever information they want and you infer the rest.  
        
        
        For example, if the user provides a topic, the LLM can infer sub topics, etc. If the user provides 
        a title, the LLM can infer descriptions, etc.

Output the updated content in a ```template code block.
"""

    user = f"""The prompt template is: 

```template
{prompt}
```
   
The updated prompt template is: 
```template

"""
    return prompt_llm(client, system, user)


def describe_prompt(client, prompt):
    system = """
You will be provided a prompt template for a prompt to be sent to an LLM. The information that the user provides is denoted with <USER: PLACEHOLDER>.
What the LLM will infer and output is denoted with <LLM: PLACEHOLDER>. In 2-3 sentences, describe what the user will
provide and what the LLM will infer and output. The output of the LLM should always be described as a "draft" that
that should be double checked by the user and serve as a starting point for the user to iterate on.
"""

    user = f"""The prompt template is: 
```template
{prompt}
```

The 2-3 sentences describing it are:

"""
    return prompt_llm(client, system, user)


def name_prompt(client, description):
    system = """
Based on the provided description, provide a 3-7 word title for the item.
"""

    user = f"""The description is: 
```template
{description}
```

The 3-7 word title describing it in a ```template code block are:
```template
"""
    name = prompt_llm(client, system, user)

    # check if name includes ```template
    if "```template" in name:
        name = extract_prompt_template(name)

    return name
    # return prompt_llm(client, system, user)

def tag_prompt(client, description):
    system = """
Based on the provided description, provide a 3-5 tags for the item as a comma separated list.
"""

    user = f"""The description is: 
```template
{description}
```

The 3-5 tags in a ```template code block are:
```template
"""

    tags = prompt_llm(client, system, user)
    tags = extract_prompt_template(tags)
    tags = tags.split(",")
    return [tag.strip() for tag in tags]


def templatize_user_tags(text):
    # Define a pattern that matches "<USER: ...>" and captures the content inside
    pattern = re.compile(r'<USER:\s*([^>]*)>', re.IGNORECASE)

    # Replacement function that formats the match as "{{...}}"
    def replacement(match):
        # Retrieve the matched group (the content within "<USER: ...>")
        content = match.group(1).strip()
        # Return the content formatted inside double curly braces
        return f"{{{{{content}}}}}"

    # Perform the substitution and return the result
    return pattern.sub(replacement, text)

def generate_idea(client, task):

    try:
        print(f"Generating idea for: {task}")

        result = generate_prompt_idea(client, task)
        result = extract_prompt_template(result)
        result = assign_roles_to_prompt_inputs(client, result)
        result = extract_prompt_template(result)

        templatized = templatize_user_tags(result)
        description = describe_prompt(client, result)
        name = name_prompt(client, description)
        tags = tag_prompt(client, description)

        debug = False
        if debug:
            print("================ Name ==============")
            print(name)

            print("================ Tags ==============")
            print(tags)

            print("================ Description ==============")
            print(description)

            print("================ Prompt Template ==============")
            print(templatized)


        print(f"Idea generated for: {task}")

        return {
            "name": name,
            "tags": tags,
            "description": description,
            "prompt": templatized
        }
    except Exception as e:
        # Try again
        print(f"An error occurred while generating an idea: {e}")
        print("Trying again...")
        return generate_idea(client, task)


def generate_10_ideas(client, task):
    try:
        result = prompt_llm(client,
                            """
                            These are the bounds that we are going to place on how we use ChatGPT in the workplace:
                            We are going to use the following framework in exploring how to use Generative AI to aid people:
                            1. Better decision making by having the LLM give them multiple possible approaches to solving a problem,
                            multiple potential interpretations of data, identifying assumptions in their decisions and helping them
                            evaluate the validity of those assumptions, often by challenging them.
                            2. Coming up with innovative ideas by serving as a brainstorming partner that offers lots of different
                            and diverse options for any task.
                            3. Simultaneously applying multiple structured approaches to representing and solving problems.
                            4. Allowing people to iterate faster and spend more time exploring possibilities by creating initial
                            drafts that are good starting points.
                            5. Aiding in summarization, drafting of plans, identification of supporting quotations or evidence,
                            identification of assumptions, in 3-5 pages of text. Provide one approach to using ChatGPT to perform
                            the following and one specific prompt that would be used for this.
    
                            Whatever I give you, generate 10 1-sentence ideas for how to use ChatGPT to aid in this task. 
                            Each sentence should be a complete idea.
                            
                            LIST EACH SENTENCE ON A SEPARATE LINE in a ```template code block.
                            """,
                            f"""
                   Generate 10 ideas for: {task}
                   
                   The 10 ideas on separate lines in a ```template code block are:
                   ```template
                   
                   """
                            )
        ideas_str = extract_prompt_template(result)
        return ideas_str.strip().split("\n")
    except Exception as e:
        # Try again
        print(f"An error occurred while generating 10 ideas: {e}")
        print("Trying again...")
        return generate_10_ideas(client, task)


fallback_to_ideas = True
def generate_ideas_in_parallel(category, client, task, times):

    the_10_ideas = category.get('top_ideas', None)
    if the_10_ideas is None and fallback_to_ideas and 'ideas' in category:
        the_10_ideas = category.get('ideas', None)
    elif the_10_ideas is None:
        the_10_ideas = generate_10_ideas(client, task)

    print(f"10 ideas generated for: {task} -- {the_10_ideas}")

    results = []
    remaining = times
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Schedule the function to be executed multiple times with the same arguments
        futures = {executor.submit(generate_idea, client, the_10_ideas[i % len(the_10_ideas)]) for i in range(times)}
        for future in concurrent.futures.as_completed(futures):
            try:
                timeout_duration = 60 * 3  # 3 minutes
                # Get the result of each future as they complete
                results.append(future.result(timeout=timeout_duration))
                remaining -= 1
                print(f"Remaining ideas to generate: {remaining}")
            except Exception as e:
                # Handle exception accordingly
                print(f"An exception occurred: {e}")

    return results

# Placeholder function to mimic creating and loading categories into the database.
dynamodb = boto3.resource('dynamodb')
# Assuming the DynamoDB table name is set as an environment variable
category_table = dynamodb.Table(MARKET_CATEGORIES_DYNAMO_TABLE)

def to_valid_yaml_key(s):
    # Strip leading and trailing whitespace
    s = s.strip()

    # Replace spaces with underscores or hyphens
    s = re.sub(r'\s+', '_', s)

    # Remove any characters that are invalid for YAML keys
    s = re.sub(r'[^\w\s-]', '', s)

    # If the resulting string is potentially ambiguous or empty,
    # it can be enclosed in quotes to make it a valid YAML key
    if not s or re.match(r'^[0-9-]', s) or ':' in s or re.search(r'\s', s):
        s = f'"{s}"'

    return s

def populate_category(category, name, path, description=None, tags=None):
    # Convert the snake_case name into title case for presentation
    readable_name = ' '.join(word.capitalize() for word in name.split('_'))

    items = generate_ideas_in_parallel(category, get_openai_client(), readable_name, 10)

    for item in items:
        #print("Generating idea #" + str(i))
        #item = generate_idea(get_openai_client(), readable_name)
        item['path'] = path
        parent = {
            to_valid_yaml_key(item['name']): item
        }
        def literal_presenter(dumper, data):
            if '\n' in data:
                return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
            else:
                return dumper.represent_scalar('tag:yaml.org,2002:str', data)

        yaml.add_representer(str, literal_presenter)

        print("Saving idea for category: " + path)
        # Save the list of dictionaries to a YAML file
        with open('output.yaml', 'a') as file:
            yaml.dump(parent, file, default_flow_style=False)



# Function that constructs the full path for each subcategory by concatenating parent paths.
def construct_path_and_load(parent_path, category):

    print(f"Processing path: {parent_path}");

    if isinstance(category, dict):
        # Extract the description and tags if they are provided at the current level
        description = category.get('description', '')
        tags = category.get('tags', [])

        sub_categories = [(k, v) for k, v in category.items() if k not in ['id','path','description', 'tags', 'ideas', 'top_ideas']]

        # Creating a category for this level.
        if len(sub_categories) == 0:
            category_name = parent_path.split('/')[-1]  # Get the last part of the path as the name
            populate_category(category, category_name, parent_path, description, tags)


        # Process any subcategories.
        for subcategory_name, subcategory_content in sub_categories:
            subcategory_path = f"{parent_path}/{convert_to_snake_case(subcategory_name)}"
            construct_path_and_load(subcategory_path, subcategory_content)





# Helper function to convert strings into snake_case for consistent path names.
def convert_to_snake_case(text):
    return text.lower().replace(' ', '_').replace('-', '_')

# Set up command-line argument parsing.


# Load the YAML file specified as a command-line argument.
with open(args.filename, 'r') as stream:
    try:
        taxonomy = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        print(exc)
        exit()

# Start the loading process from the top level of the taxonomy.
for main_category_name, main_category_content in taxonomy["Marketplace_Taxonomy"].items():
    main_category_path = '/' + convert_to_snake_case(main_category_name)
    construct_path_and_load(main_category_path, main_category_content)
