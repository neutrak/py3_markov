import json

dflt_cfg='confuseus_cfg.json'

def read_json_file(fname):
	fp=open(fname)
	fcontent=fp.read()
	fp.close()
	
	try:
		json_tree=json.loads(fcontent)
	except ValueError:
		json_tree=None
	
	return json_tree

def get_json_param(json_tree,param):
	if(json_tree==None):
		return None
	
	try:
		return json_tree[param]
	except KeyError:
		return None

