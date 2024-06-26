import requests
import os
import re
import pandas as pd
from solr import SolrEngine
from IPython.display import display,HTML
from os import path
from tqdm import tqdm

SEARCH_SOLR_HOST = "search-solr"
SEARCH_NOTEBOOK_HOST="search-notebook"
SEARCH_ZK_HOST="search-zk"
#SEARCH_SOLR_HOST = "localhost"
#SEARCH_NOTEBOOK_HOST="localhost"
#SEARCH_ZK_HOST="localhost"
SEARCH_SOLR_PORT = os.getenv('SEARCH_SOLR_PORT') or '8983'
SEARCH_NOTEBOOK_PORT= os.getenv('SEARCH_NOTEBOOK_PORT') or '8888'
SEARCH_ZK_PORT= os.getenv('SEARCH_ZK_PORT') or '2181'
SEARCH_WEBSERVER_HOST = os.getenv('SEARCH_WEBSERVER_HOST') or 'localhost'
SEARCH_WEBSERVER_PORT = os.getenv('SEARCH_WEBSERVER_PORT') or '2345'
ENGINE = SolrEngine()

SOLR_URL = f'http://{SEARCH_SOLR_HOST}:{SEARCH_SOLR_PORT}/solr'
SOLR_COLLECTIONS_URL = f'{SOLR_URL}/admin/collections'
WEBSERVER_URL = f'http://{SEARCH_WEBSERVER_HOST}:{SEARCH_WEBSERVER_PORT}'

def healthcheck():
  status_url = f'{SOLR_URL}/admin/zookeeper/status'

  try:
    if (get_engine().health_check()):
      print ("Solr is up and responding.")
      print ("Zookeeper is up and responding.\n")
      print ("All Systems are ready. Happy Searching!")
  except:
      print ("Error! One or more containers are not responding.\nPlease follow the instructions in Appendix A.")

def get_engine():
  return ENGINE

def print_status(solr_response):
  print("Status: Success" if solr_response["responseHeader"]["status"] == 0 else "Status: Failure; Response:[ " + str(solr_response) + " ]" )

def create_collection(collection_name):
    #Wipe previous collection
  wipe_collection_params = [
      ('action', "delete"),
      ('name', collection_name)
  ]

  print(f"Wiping '{collection_name}' collection")
  response = requests.post(SOLR_COLLECTIONS_URL, data=wipe_collection_params).json()

  #Create collection
  create_collection_params = [
      ('action', "CREATE"),
      ('name', collection_name),
      ('numShards', 1),
      ('replicationFactor', 1) ]

  print(create_collection_params)

  print(f"Creating '{collection_name}' collection")
  response = requests.post(SOLR_COLLECTIONS_URL, data=create_collection_params).json()
  print_status(response)

def enable_ltr(collection_name):

    collection_config_url = f'{SOLR_URL}/{collection_name}/config'

    del_ltr_query_parser = { "delete-queryparser": "ltr" }
    add_ltr_q_parser = {
     "add-queryparser": {
        "name": "ltr",
            "class": "org.apache.solr.ltr.search.LTRQParserPlugin"
        }
    }

    print(f"Del/Adding LTR QParser for {collection_name} collection")
    response = requests.post(collection_config_url, json=del_ltr_query_parser)
    print(response)
    print_status(response.json())
    response = requests.post(collection_config_url, json=add_ltr_q_parser).json()
    print_status(response)

    del_ltr_transformer = { "delete-transformer": "features" }
    add_transformer =  {
      "add-transformer": {
        "name": "features",
        "class": "org.apache.solr.ltr.response.transform.LTRFeatureLoggerTransformerFactory",
        "fvCacheName": "QUERY_DOC_FV"
    }}

    print(f"Adding LTR Doc Transformer for {collection_name} collection")
    response = requests.post(collection_config_url, json=del_ltr_transformer).json()
    print_status(response)
    response = requests.post(collection_config_url, json=add_transformer).json()
    print_status(response)
    
def delete_field(collection_name, field_name):
    #clear out old field to ensure this function is idempotent
    delete_field = {"delete-field":{ "name":field_name }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field).json()

def clear_copy_fields(collection_name):
    copy_fields = requests.get(f"{SOLR_URL}/{collection_name}/schema/copyfields?wt=json").json()
    print("Deleting all copy fields")
    for field in copy_fields['copyFields']:
        source = field['source']
        dest = field['dest']
        rule = {"source": source, "dest": dest}
        delete_copy_field = {"delete-copy-field": rule}
        response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_copy_field).json()
        print_status(response)


def add_text_field_type(collection_name, analyzer, name,
                        omitTermFreqAndPositions=False,
                        omitNorms=False):
    """Create a field type and a corresponding dynamic field."""
    field_type_name = "text_" + name
    dynamic_field_name = "*_" + name
    print(f"Creating Field Type {field_type_name}")
    print(f" with Dynamic Field {dynamic_field_name}")

    delete_dynamic_field = {
        "delete-dynamic-field": {
            "name": dynamic_field_name
        }
    }
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_dynamic_field)
    print("Delete dynamic field")
    print_status(response.json())

    delete_field_type = {
        "delete-field-type": {
            "name": field_type_name
        }
    }
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field_type)
    print("Delete field type")
    print_status(response.json())

    add_field_type = {
        "add-field-type": {
            "name": field_type_name,
            "class":"solr.TextField",
            "positionIncrementGap":"100",
            "analyzer": analyzer,
            "omitTermFreqAndPositions": omitTermFreqAndPositions,
            "omitNorms": omitNorms
        }
    }
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_field_type)
    print("Create field type")
    print_status(response.json())

    add_dynamic_field = {
        "add-dynamic-field": {
            "name": dynamic_field_name,
            "type": field_type_name,
            "stored": True
        }
    }
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_dynamic_field)
    print_status(response.json())

    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_dynamic_field)
    print("Create dynamic field")
    print_status(response.json())


def add_copy_field(collection_name, src_field, dest_fields):
    rule = {"source": src_field, "dest": dest_fields}
    add_copy_field = {"add-copy-field": rule}

    print(f"Adding Copy Field {src_field} -> {dest_fields}'")
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_copy_field).json()
    print_status(response)


def upsert_text_field(collection_name, field_name):
    #clear out old field to ensure this function is idempotent
    delete_field = {"delete-field":{ "name":field_name }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field).json()

    print("Adding '" + field_name + "' field to collection")
    add_field = {"add-field":{ "name":field_name, "type":"text_general", "stored":"true", "indexed":"true", "multiValued":"false" }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_field).json()
    print_status(response)

def upsert_double_field(collection_name, field_name):
    #clear out old field to ensure this function is idempotent
    delete_field = {"delete-field":{ "name":field_name }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field).json()

    print("Adding '" + field_name + "' field to collection")
    add_field = {"add-field":{ "name":field_name, "type":"pdouble", "stored":"true", "indexed":"true", "multiValued":"false" }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_field).json()
    print_status(response)
    
def upsert_integer_field(collection_name, field_name):
    #clear out old field to ensure this function is idempotent
    delete_field = {"delete-field":{ "name":field_name }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field).json()

    print("Adding '" + field_name + "' field to collection")
    add_field = {"add-field":{ "name":field_name, "type":"pint", "stored":"true", "indexed":"true", "multiValued":"false" }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_field).json()
    print_status(response)

def upsert_keyword_field(collection_name, field_name):
    #clear out old field to ensure this function is idempotent
    delete_field = {"delete-field":{ "name":field_name }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field).json()

    print("Adding '" + field_name + "' field to collection")
    add_field = {"add-field":{ "name":field_name, "type":"string", "stored":"true", "indexed":"true", "multiValued":"true", "docValues":"true" }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_field).json()

    print_status(response)
    
def upsert_string_field(collection_name, field_name):
    #clear out old field to ensure this function is idempotent
    delete_field = {"delete-field":{ "name":field_name }}

    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field).json()

    print("Adding '" + field_name + "' field to collection")
    add_field = {"add-field":{ "name":field_name, "type":"string", "stored":"true", "indexed":"false", "multiValued":"false", "docValues":"true" }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_field).json()
    print_status(response)
    
def upsert_boosts_field_type(collection_name, field_type_name):
    delete_field_type = {"delete-field-type":{ "name":field_type_name }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field_type).json()

    print(f"Adding '{field_type_name}' field type to collection")
    add_field_type = { 
        "add-field-type" : {
            "name": field_type_name,
            "class":"solr.TextField",
            "positionIncrementGap":"100",
            "analyzer" : {
                "tokenizer": {
                    "class":"solr.PatternTokenizerFactory",
                    "pattern": "," },
                 "filters":[
                    { "class":"solr.LowerCaseFilterFactory" },
                    { "class":"solr.DelimitedPayloadFilterFactory", "delimiter": "|", "encoder": "float" }]}}}

    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_field_type).json()
    print_status(response)
    
def upsert_integer_field(collection_name, field_name):
    #clear out old field to ensure this function is idempotent
    delete_field = {"delete-field":{ "name":field_name }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field).json()

def upsert_boosts_field(collection_name, field_name, field_type_name="boosts"):
    
    #clear out old field to ensure this function is idempotent
    delete_field = {"delete-field":{ "name":field_name }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=delete_field).json()

    upsert_boosts_field_type(collection_name, field_type_name);
    
    print(f"Adding '{field_name}' field to collection")
    add_field = {"add-field":{ "name":field_name, "type":"boosts", "stored":"true", "indexed":"true", "multiValued":"true" }}
    response = requests.post(f"{SOLR_URL}/{collection_name}/schema", json=add_field).json()

    print_status(response)
    
def num2str(number):
  return str(round(number,4)) #round to 4 decimal places for readibility

def vec2str(vector):
  return "[" + ", ".join(map(num2str,vector)) + "]"

def tokenize(text):
  return text.replace(".","").replace(",","").lower().split()

def img_path_for_upc(upc):
    # file_path = os.path.dirname(os.path.abspath(__file__))
    expected_jpg_path = f"../data/images/{upc}.jpg"
    unavailable_jpg_path = "../data/images/unavailable.jpg"
    return expected_jpg_path if os.path.exists(expected_jpg_path) else unavailable_jpg_path

def display_search(query, documents):
  display(HTML(f"<strong>Query</strong>: <i>{query}</i><br/><br/><strong>Results:</strong>"))
  display(HTML(documents))
  
def render_search_results(query, results):
    file_path = os.path.dirname(os.path.abspath(__file__))
    search_results_template_file = os.path.join(file_path + "/data/templates/", "search-results.html")
    with open(search_results_template_file) as file:
        file_content = file.read()

        template_syntax = "<!-- BEGIN_TEMPLATE[^>]*-->(.*)<!-- END_TEMPLATE[^>]*-->"
        header_template = re.sub(template_syntax, "", file_content, flags=re.S)

        results_template_syntax = "<!-- BEGIN_TEMPLATE: SEARCH_RESULTS -->(.*)<!-- END_TEMPLATE: SEARCH_RESULTS[^>]*-->"
        x = re.search(results_template_syntax, file_content, flags=re.S)
        results_template = x.group(1)

        separator_template_syntax = "<!-- BEGIN_TEMPLATE: SEPARATOR -->(.*)<!-- END_TEMPLATE: SEPARATOR[^>]*-->"
        x = re.search(separator_template_syntax, file_content, flags=re.S)
        separator_template = x.group(1)

        rendered = header_template.replace("${QUERY}", query)
        for result in results:
            rendered += results_template.replace("${NAME}", result['name'] if 'name' in result else "UNKNOWN") \
                .replace("${MANUFACTURER}", result['manufacturer'] if 'manufacturer' in result else "UNKNOWN") \
                .replace("${DESCRIPTION}", result['shortDescription'] if 'shortDescription' in result else "") \
                .replace("${IMAGE_URL}", "../data/images/" + \
                         (result['upc'] if \
                          ('upc' in result and os.path.exists(file_path + "/data/images/" + result['upc'] + ".jpg") \
                         ) else "unavailable") + ".jpg")

            rendered += separator_template

        return rendered

def fetch_products(doc_ids):
    import requests
    doc_ids = ["%s" % doc_id for doc_id in doc_ids]
    query = "upc:( " + " OR ".join(doc_ids) + " )"
    params = {'q':  query, 'wt': 'json', 'rows': len(doc_ids)}
    resp = requests.get(f"{SOLR_URL}/products/select", params=params)
    df = pd.DataFrame(resp.json()['response']['docs'])
    df['upc'] = df['upc'].astype('int64')

    df.insert(0, 'image', df.apply(lambda row: "<img height=\"100\" src=\"" + img_path_for_upc(row['upc']) + "\">", axis=1))

    return df

def render_judged(products, judged, grade_col='ctr', label=""):
    """ Render the computed judgments alongside the productns and description data"""
    w_prods = judged.merge(products, left_on='doc_id', right_on='upc', how='left')

    w_prods = w_prods[[grade_col, 'image', 'upc', 'name', 'shortDescription']]

    return HTML(f"<h1>{label}</h1>" + w_prods.to_html(escape=False))


def download(uris, dest='data/'):
    for uri in uris:
        download_one(uri=uri, dest=dest, force=False, fancy=False)

def download_one(uri, dest='data/', force=False, fancy=False):
    import os

    if not os.path.exists(dest):
        os.makedirs(dest)

    if not os.path.isdir(dest):
        raise ValueError("dest {} is not a directory".format(dest))

    filename = uri[uri.rfind('/') + 1:]
    filepath = os.path.join(dest, filename)
    if path.exists(filepath):
        if not force:
            print(filepath + ' already exists')
            return
        print("exists but force=True, Downloading anyway")

    if not fancy:
        with open(filepath, 'wb') as out:
            print('GET {}'.format(uri))
            resp = requests.get(uri, stream=True)
            for chunk in resp.iter_content(chunk_size=1024):
                if chunk:
                    out.write(chunk)
    else:
        resp = requests.get(uri, stream=True)
        total = int(resp.headers.get('content-length', 0))
        with open(filepath, 'wb') as file, tqdm(
                desc=filepath,
                total=total,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
        ) as bar:
            for data in resp.iter_content(chunk_size=1024):
                size = file.write(data)
                bar.update(size)


"""
class environment:

  self._SEARCH_SOLR_HOST = "search-solr"
  self._SEARCH_NOTEBOOK_HOST="search-notebook"
  self._SEARCH_ZK_HOST="search-zk"
  self._SEARCH_SOLR_PORT = "8983"
  self._SEARCH_NOTEBOOK_PORT="8888"
  self._SEARCH_ZK_PORT="2181"
  self._SEARCH_SOLR_URL=''
  self._SEARCH_SOLR_COLLECTIONS_API=''

  if "SEARCH_HOST" in os.environ:
    self._SEARCH_SOLR_HOST=os.environ['SEARCH_HOST']
    self._SEARCH_NOTEBOOK_HOST=os.environ['SEARCH_HOST']
    self._SEARCH_ZK_HOST=os.environ['SEARCH_HOST']

  if "SEARCH_SOLR_HOST" in os.environ:
    self._SEARCH_SOLR_HOST=os.environ['SEARCH_SOLR_HOST']

  if "SEARCH_NOTEBOOK_HOST" in os.environ:
    self._SEARCH_NOTEBOOK_HOST=os.environ['SEARCH_NOTEBOOK_HOST']

  if "SEARCH_ZK_HOST" in os.environ:
    self._SEARCH_ZK_HOST=os.environ['SEARCH_ZK_HOST']

  if "SEARCH_SOLR_PORT" in os.environ:
    self._SEARCH_SOLR_PORT=os.environ['SEARCH_SOLR_PORT']

  if "SEARCH_NOTEBOOK_HOST" in os.environ:
    self._SEARCH_NOTEBOOK_PORT=os.environ['SEARCH_NOTEBOOK_PORT']

  if "SEARCH_ZK_HOST" in os.environ:
    self._SEARCH_ZK_PORT=os.environ['SEARCH_ZK_PORT']

  self._SEARCH_SOLR_URL = 'http://' + SEARCH_SOLR_HOST + ':' + SEARCH_SOLR_PORT + '/solr/'
  self._SEARCH_SOLR_COLLECTIONS_API = SEARCH_SOLR_URL + 'admin/collections'

  @property
  def SOLR_HOST(self):
    return self._SEARCH_SOLR_HOST

  @property
  def NOTEBOOK_HOST(self):
    return self._SEARCH_SOLR_HOST

  @property
  def ZK_HOST(self):
    return self._SEARCH_ZK_HOST

  @property
  def SOLR_PORT(self):
    return self._SEARCH_SOLR_PORT

  @property
  def NOTEBOOK_PORT(self):
    return self._SEARCH_NOTEBOOK_PORT

  @property
  def ZK_PORT(self):
    return self._SEARCH_ZK_PORT

  @property
  def SOLR_URL(self):
    return self._SEARCH_SOLR_URL

  @property
  def SOLR_COLLECTIONS_API(self):
    return self._SEARCH_SOLR_COLLECTIONS_API
"""
