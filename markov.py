#!/usr/bin/env python3

import config
import random
import sys

try:
	import postgresql
except ImportError:
	use_pg=False
	db_login=None

#this is just a data structure to store state transition information
#python has no notion of a "struct" so this is as close as we can get
class state_transition:
	def __init__(self,prefix,suffix):
		self.prefix=prefix
		self.suffix=suffix
		self.count=1

class db_info:
	def __init__(self,user,passwd,db_name):
		self.user=user
		self.passwd=passwd
		self.db_name=db_name

VERSION='1.0.0'

#get the next token out of the given text
def next_token(text):
	token=text
	
	#how many characters of the starting text were used to get this token
	chars_used=0
	
	#remove leading whitespace
	while(token.startswith(' ') or token.startswith("\n") or token.startswith("\t")):
		token=token[1:]
		chars_used+=1
	
	space_idx=token.find(' ')
	newline_idx=token.find("\n")
	tab_idx=token.find("\t")
	
	#if there is a space, newline, or tab,
	#then stop there
	if(space_idx>=0):
		token=token[0:space_idx]
		chars_used+=space_idx
	elif(newline_idx>=0):
		token=token[0:newline_idx]
		chars_used+=newline_idx
	elif(tab_idx>=0):
		token=token[0:tab_idx]
		chars_used+=tab_idx
	#if there wasn't whitespace,
	#the whole rest of the text is a token
	else:
		chars_used+=len(token)
	
#	print('next_token debug 0, token='+token+', chars_used='+str(chars_used)+', remaining_text='+text[chars_used:])
	
	#and return whatever we got, along with the remainder
	return (token,text[chars_used:])

#TODO: fix this binary search to be faster,
#it's algorithmically fast (O(log(n)))
#but it does a lot of checks and there's probably some better way to do some of it

#find the index of the first element with the given prefix
#if a suffix is given, checks for that too
#if the prefix was not found, returns the index it should go at
#the success element in the returned tuple specifies whether or not the prefix was found
def binsearch_states(state_change,min_idx,max_idx,prefix,suffix=None):
#	print('binsearch_states debug 0, len(state_change)='+str(len(state_change))+', min_idx='+str(min_idx)+', max_idx='+str(max_idx))
	
	success=False
	
	#if there are no elements,
	#then all new elements get inserted at 0
	#and we didn't find anything, no matter what it was
	if(len(state_change)==0):
		return (success,0)
	
	#if we restricted the range to a single element,
	#then check against that
	if(min_idx==max_idx):
#		print('binsearch_states debug 0.5, min_idx==max_idx at '+str(min_idx))
		
		#if we succeeded in a binary search for the prefix
		if(prefix==state_change[min_idx].prefix):
			#if there was no suffix specified, then we're done
			if(suffix==None):
				success=True
			#otherwise we have to find the correct spot for that suffix
			else:
#				print('binsearch_states debug 1, searching for suffix '+suffix+' starting at index '+str(min_idx))
				
				#do a linear search for the suffix among elements which share the same prefix
				#this is slower than a binary search, but simpler,
				#and the number of elements which share a prefix should be small
				#relative to the whole state change
				while(min_idx<len(state_change) and prefix==state_change[min_idx].prefix and suffix>state_change[min_idx].suffix):
					min_idx+=1
				
				if(min_idx<len(state_change)):
					if(suffix==state_change[min_idx].suffix):
						success=True
		#if we are larger than this prefix, then insert after it
		elif(prefix>state_change[min_idx].prefix):
#			print('binsearch_states debug 1.5, min_idx='+str(min_idx))
			min_idx+=1
		#implicitly, if we are not equal or larger,
		#then we must be smaller than the array element prefix
		#in this case, insert at min_idx (before the array element), so no else case is needed here
		
		return (success,min_idx)
	#if there was a range, but the range all has the same prefix,
	#then go to the minimum of the range (after which we will hit the above if)
	elif(state_change[min_idx].prefix==state_change[max_idx].prefix):
		return binsearch_states(state_change,min_idx,min_idx,prefix,suffix)
	#if the range is only a single entry, then guess_idx will end up at an endpoint
	#because of that, we need to return here somehow
	elif(max_idx-min_idx==1):
#		print('binsearch_states debug 2, restricted range to ['+str(min_idx)+','+str(max_idx)+']')
		if(prefix<state_change[min_idx].prefix):
			return (success,min_idx)
		elif(prefix>state_change[max_idx].prefix):
			return (success,max_idx+1)
		elif(prefix==state_change[min_idx].prefix):
			return binsearch_states(state_change,min_idx,min_idx,prefix,suffix)
		elif(prefix==state_change[max_idx].prefix):
			if(suffix==None):
				success=True
			else:
				if(suffix>state_change[max_idx].suffix):
					max_idx+=1
				elif(suffix==state_change[max_idx].suffix):
					success=True
			return (success,max_idx)
		else:
			return (success,max_idx)
		
	
	
	#take a guess at the middle
	guess_idx=int((min_idx+max_idx)/2)
	
	#restrict the range in a binary-search type way
	
	if(prefix<state_change[guess_idx].prefix):
		return binsearch_states(state_change,min_idx,guess_idx,prefix,suffix)
	elif(prefix>state_change[guess_idx].prefix):
		return binsearch_states(state_change,guess_idx,max_idx,prefix,suffix)
	
	#if we got here and didn't return,
	#then we found the prefix at the guess_idx value
	#so linearly go back until we get to the first thing with that prefix, then return
	while(guess_idx>=0 and prefix==state_change[guess_idx].prefix):
		guess_idx-=1
	if(prefix!=state_change[guess_idx].prefix):
		guess_idx+=1
	
	#because we already have a nice base return case if min_idx==max_idx, we'll use that
	return binsearch_states(state_change,guess_idx,guess_idx,prefix,suffix)

#search states for a suffix
#this is O(n) because the state_change array is sorted by prefix
def suffix_get_states(state_change,suffix):
	acc=[]
	for state in state_change:
		if(state.suffix==suffix):
			acc.append(state)
	return acc
	
def pg_connect(db_login):
	db_handle=postgresql.open('pq://'+db_login.user+':'+db_login.passwd+'@localhost/'+db_login.db_name)
	return db_handle

def pg_run_query(db_login,pg_query,pg_params):
	db_handle=pg_connect(db_login)
	postgre_ret=db_handle.prepare(pg_query)
	results=postgre_ret(*pg_params)
	db_handle.close()
	
	return results

def pg_search(db_handle,db_login,prefix,suffix=None):
	pg_params=[]
	
	pg_query=''
	if(suffix!=None):
		pg_query='SELECT * FROM states WHERE prefix=$1 AND suffix=$2'
	else:
		pg_query='SELECT * FROM states WHERE prefix=$1'
	
	postgre_ret=db_handle.prepare(pg_query)
	results=[]
	if(suffix!=None):
		results=postgre_ret(' '.join(prefix),suffix)
	else:
		results=postgre_ret(' '.join(prefix))
	
	#python's ternary operator can go fuck itself
	success=(True if len(results)>0 else False)
	
	states=[]
	if(success):
		for row in results:
			new_state=state_transition(row['prefix'].split(' '),row['suffix'])
			new_state.count=int(row['count'])
			states.append(new_state)
	
	return (success,states)

def pg_search_suffix(db_handle,db_login,suffix):
	pg_params=[]
	
	pg_query='SELECT * FROM states WHERE suffix=$1'
	
	postgre_ret=db_handle.prepare(pg_query)
	results=postgre_ret(suffix)
	
	#python's ternary operator can go fuck itself
	success=(True if len(results)>0 else False)
	
	states=[]
	if(success):
		for row in results:
			new_state=state_transition(row['prefix'].split(' '),row['suffix'])
			new_state.count=int(row['count'])
			states.append(new_state)
	
	return (success,states)

def pg_insert(db_handle,db_login,prefix,suffix,count):
	pg_query='INSERT INTO states (prefix,suffix,count) VALUES ($1,$2,$3)'
	
	postgre_ret=db_handle.prepare(pg_query)
	results=postgre_ret(' '.join(prefix),suffix,count)
	
	return None

def pg_update(db_handle,db_login,prefix,suffix,count):
	pg_query='UPDATE states SET count=$1 WHERE prefix=$2 AND suffix=$3'
	
	postgre_ret=db_handle.prepare(pg_query)
	results=postgre_ret(count,' '.join(prefix),suffix)
	
	return None

def output_states(state_change):
	print('[')
	for state in state_change:
		print('{ prefix:'+str(state.prefix)+', suffix:'+str(state.suffix)+', count:'+str(state.count)+' }')
	print(']')
	print('')

def is_state_sorted(state_change):
	for i in range(0,len(state_change)-2):
		if(state_change[i].prefix>state_change[i+1].prefix):
			print('Err: states not sorted (prefix error) (element '+str(i)+')')
			return False
		elif(state_change[i].prefix==state_change[i+1].prefix):
			if(state_change[i].suffix>state_change[i+1].suffix):
				print('Err: states not sorted (suffix error) (element '+str(i)+')')
				return False
	return True

#add the given text to the chain
#the text follows from the given prefix
#the initial prefix consists of null strings
#the length of the prefix array is used throughout the chain
#
#the chain_ended parameter is for if the token delimiter was a newline,
#if so, then add a null suffix
#this serves to help avoid rambling by stopping at roughly correct spots
#( or horribly incorrect spots :P )
def chain_from(text,state_change=[],prefix=['',''],verbose_dbg=False,check_sorted=False,chain_ended=False,use_pg=False,db_login=None):
	token,text=next_token(text)
	
	if(verbose_dbg):
		print('chain_from debug 0, prefix='+str(prefix)+', token='+token)
	
	#if the chain has ended, then we hit the end of the text (or end of line)
	#this is the base case to end recursion
	if(chain_ended):
		if(use_pg):
			return None
		else:
			return state_change
	
	transition_found=False
	
	if(use_pg):
		if(verbose_dbg):
			print('chain_from debug 0.5, inserting or updating (prefix,suffix,count) ('+str(prefix)+',\''+token+'\','+str(1)+')')
		
		db_handle=pg_connect(db_login)
		
		success,results=pg_search(db_handle,db_login,prefix,token)
		if(success):
			results[0].count+=1
			pg_update(db_handle,db_login,prefix,token,int(results[0].count))
		else:
			pg_insert(db_handle,db_login,prefix,token,1)
		
		db_handle.close()
	else:
		#do a binary search to find this state
		#(or, if not found, to find where it should go)
		success,ins_idx=binsearch_states(state_change,0,len(state_change)-1,prefix,token)
		if(success):
			#found state, just update the count
			state_change[ins_idx].count+=1
		else:
			#didn't find state, inserting at index ins_idx
			new_state=state_transition(prefix,token)
#			state_change=state_change[0:ins_idx]+[new_state]+state_change[ins_idx:]
			state_change.insert(ins_idx,new_state)
		
		if(verbose_dbg):
			print('chain_from debug 1, current state_change array is: ')
			output_states(state_change)
		
	#this check is super expensive so it's only done when asked
	#I verified on 5000 lines test data that it works, but there might be some weird case I missed
	#I also fed in 50000 lines without checking sorting,
	#then checked sorting on the resulting state file and it was right,
	#so I'm like 95% confident in its ability
	if((not use_pg) and (check_sorted)):
		if(not is_state_sorted(state_change)):
			print('Warn: states are NOT properly sorted; sorting manually to correct the problem...')
			print('Warn (continued): If the data has been this way for a while it may now be invalid and have duplicates etc.')
			print('state change array (pre-sort) was: ')
			output_states(state_change)
			
			#this can be done in two sorts because python list sort is guaranteed stable
			state_change.sort(key=lambda state:state.suffix)
			state_change.sort(key=lambda state:state.prefix)
			
	
	#update the prefix for the next token
	prefix=[prefix[1],token]
	
	chain_ended=False
	if(token==''):
		chain_ended=True
	
	#there may be tokens still left, so try on those
	return chain_from(text,state_change,prefix,chain_ended=chain_ended,use_pg=use_pg,db_login=db_login)

#generate text based on the given state change array
#default prefix of ['',''] generates from starting states
#note that because this is recursive and python doesn't TCO,
#word_limit must be less than max recursion depth
def generate(state_change=[],prefix=['',''],word_limit=40,acc='',verbose_dbg=True,use_pg=False,db_login=None,back_gen=False,dbg_str=''):
	#trim leading whitespace just to be pretty
	acc=acc.lstrip(' ')
	
	#if we hit the word limit, return now
	if(word_limit<1):
		return (acc.rstrip(' '),dbg_str)
	
	#total count of all states that come from the given prefix
	#this is used so we can calculate probabilities based on state counts
	prefix_count=0
	
	#the states which indicate transitions starting with the given prefix
	transition_states=[]
	
	if(use_pg):
		db_handle=pg_connect(db_login)
		
		success,results=pg_search(db_handle,db_login,prefix,suffix=None)
		if(success):
			transition_states=results
			
			prefix_count=len(transition_states)
		else:
			#since prefix_count is already 0, nothing needs to be done here
			#acc will be returned shortly
			pass
		
		db_handle.close()
	else:
		#binary search for this prefix, so we get all the valid transitions quickly
		success,start_idx=binsearch_states(state_change,0,len(state_change)-1,prefix,suffix=None)
		
		#if the prefix wasn't found, then there are no transitions left
		if(not success):
			start_idx=len(state_change)
		
		for state_idx in range(start_idx,len(state_change)):
			state=state_change[state_idx]
			if(state.prefix==prefix):
				transition_states.append(state)
				prefix_count+=(state.count)
			#because state_change is sorted by prefix,
			#as soon as we find an entry with a larger prefix,
			#we can stop looking
			elif(state.prefix>prefix):
				break
	
	if(verbose_dbg):
		print('markov.generate debug 0, got '+str(len(transition_states))+' transition states for prefix '+str(prefix))
#		dbg_str+='[dbg] got '+str(len(transition_states))+' transition states for prefix '+str(prefix)+"\n"
		dbg_str+=str(prefix)+'-['+str(len(transition_states))+']->'
	
	#the states which indicate transitions starting from the given suffix
	#(1st word of accumulator)
	back_suffix=acc.split(' ')[0]
	back_transition_states=[]
	
	if(back_suffix==''):
		back_gen=False
	
	#handle transitions going backwards
	if(back_gen):
		if(use_pg):
			db_handle=pg_connect(db_login)
			
			success,back_transition_states=pg_search_suffix(db_handle,db_login,back_suffix)
			if(success):
				back_transition_states_states=results
			
			db_handle.close()
		else:
			back_transition_states=suffix_get_states(state_change,back_suffix)
	
	if(verbose_dbg and back_gen):
		print('markov.generate debug 1, got '+str(len(back_transition_states))+' transition states for suffix '+str(back_suffix))
#		dbg_str+='[dbg] got '+str(len(back_transition_states))+' transition states for suffix '+str(back_suffix)+"\n"
		dbg_str+='<-['+str(len(back_transition_states))+']-'+str(back_suffix)
	
	if(back_gen and (len(back_transition_states)>0)):
		back_state_idx=random.randint(0,len(back_transition_states)-1)
		for state in back_transition_states:
			if(back_state_idx<state.count):
				if(state.prefix[-1]==''):
					back_gen=False
				else:
					acc=state.prefix[-1]+' '+acc
					#remember this counts as a word
					word_limit-=1
				#stop once one word is prepended
				break
			back_state_idx-=state.count
	
	#no transition state was found (nothing with that prefix),
	#return accumulator now
	if(prefix_count==0):
		return (acc.rstrip(' '),dbg_str)
	
	#now make a random number from 0 to prefix_count,
	#to determine which state to transition to
	next_state_idx=random.randint(0,prefix_count-1)
	
	for state in transition_states:
		#we found our next state, so go to it (recursively)
		if(next_state_idx<state.count):
			return generate(state_change,[prefix[1],state.suffix],word_limit-1,acc+' '+state.suffix,use_pg=use_pg,db_login=db_login,back_gen=back_gen,dbg_str=dbg_str)
		
		#we didn't find the state yet,
		#but there was some probability that it was this state
		#so remove that section of the probability for the next state
		next_state_idx-=state.count
	
	#if we got here and didn't return,
	#then there was something with that prefix,
	#but we didn't randomly pick it correctly
	#this should have a 0 probability of happening, so something went wrong
	#print an error and return accumulator
	print('Err: generate did not correctly determine which suffix to use, we messed up bad!')
	
	return (acc.rstrip(' '),dbg_str)

#generate from a given starting string
def gen_from_str(state_change,use_pg,db_login,start_str,start_word_cnt=1,prefix_len=2,retries_left=0,qa_sets=[]):
	output=''
	dbg_str=''

	#sometimes back-generate and sometimes don't
	#just to mess with people :)
#	back_gen=bool(random.getrandbits(1))
	
	#back_gen broke cases where the user
	#intended to start from a given word
	#so it's disabled
	back_gen=False
	
	#if a matching "question" line was found, try to generate an "answer" using the "prompt"
	#and for bonus points, "quote" "stuff" VERY "unnecessarily" :P
	qa_matches=[]
	question=''
	for n in range(0,len(qa_sets)):
		#question-answer comes in sets of three
		#bad-indexing ignores your last config gracefully
		if((n%3==0) and ((n+2)<len(qa_sets))):
			#if a question which was asked was found in the qa config
			start_str_lower=start_str.lower()
			qa_strt_def=qa_sets[n].lower()
			qa_end_def=qa_sets[n+2].lower()
			if((start_str_lower.startswith(qa_strt_def)) and (start_str_lower.endswith(qa_end_def))):
				#output the appropriate response
				question=qa_strt_def
				qa_matches.append(qa_sets[n+1])
				
	
	#if we know what to say because we have a prompt for this, then just do as we're told
	#like good comrades
	#TODO: ascii art hammer and sickle
	if(len(qa_matches)>0):
		rand_idx=random.randint(0,len(qa_matches)-1)
		answer_prompt=qa_matches[rand_idx]
		prefix_words=answer_prompt.split(' ')
		while(len(prefix_words)<prefix_len):
			prefix_words=['']+prefix_words
		print('[dbg] Answering \"'+question+'\" using prompt \"'+str(prefix_words)+'\"')
		
		#start with what we're configured to start with, and go from there
		output,dbg_str=generate(state_change,prefix=prefix_words,acc=' '.join(prefix_words),use_pg=use_pg,db_login=db_login,back_gen=back_gen)
		
		if(output==''):
			output,dbg_str=generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=back_gen)
		
		return output,dbg_str
	
	#if no prompt was found (i.e. we got to this case)
	#use a random word the user said and start generating from there
	words=start_str.split(' ')
	if(len(words)>0):
		rand_word_idx=random.randint(0,len(words)-1)
		
		prefix_words=[]
		n=rand_word_idx
		while((n<len(words)) and (n<(rand_word_idx+start_word_cnt)) and (n<(rand_word_idx+prefix_len))):
			prefix_words.append(words[n])
			n+=1
		while(len(prefix_words)<prefix_len):
			prefix_words=['']+prefix_words
		
		print('Chose a random word list to start from '+str(prefix_words)+', back_gen is '+str(back_gen))
		
		#try to use a word from the user
		output,dbg_str=generate(state_change,prefix=prefix_words,acc=' '.join(prefix_words),use_pg=use_pg,db_login=db_login,back_gen=back_gen)
		
		print('start_str is '+str(start_str)+', output is '+str(output)+', retries_left='+str(retries_left))
		
		#retry if we didn't get anything good (don't just repeat the user)
		if((output==(' '.join(prefix_words)).lstrip(' ')) or (output==start_str)):
			if(retries_left>0):
				return gen_from_str(state_change,use_pg,db_login,start_str,start_word_cnt,retries_left-1)
			else:
				output=''
	if(output==''):
		output,dbg_str=generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=back_gen)
	
	return output,dbg_str


#saves the state change to a file, for easy reading later
def save_state_change_to_file(state_change,filename):
	try:
		fp=open(filename,'w')
	except IOError:
		print('Err: could not write to state_change file')
		return
	
	#for each state transition, write a line to the file
	for state in state_change:
		#the line for this state
		#a state line (get it? like, territory...)
		state_line=str(state.count)+' '+state.suffix
		for token in state.prefix:
			state_line+=' '+token
		state_line+="\n"
		fp.write(state_line)
	
	fp.close()
	return

#reads the state change from a file it was previously written to
def read_state_change_from_file(filename):
	state_change=[]
	
	try:
		fp=open(filename,'r')
		fcontent=fp.read()
		fp.close()
	except IOError:
		print('Err: could not read from state_change file')
		return state_change
	except UnicodeDecodeError:
		print('Err: could not decode fomr state_change file!!!!!; this is BAD')
		return state_change
#	except:
#		print('Err: your shit\'s all fucked up')
#		return state_change
	
	#each line in this file corresponds to a state,
	#except for those starting with #, which are comments
	#and blank lines, which are blank (of course!)
	for line in fcontent.split("\n"):
		line=line.lstrip(' ')
		if((len(line)<1) or (line[0]=='#')):
			continue
		
		columns=line.split(' ')
		
		count=int(columns[0])
		suffix=columns[1]
		prefix=columns[2:]
		new_state=state_transition(prefix,suffix)
		
		state_change.append(new_state)
	
	#sort by state prefix
	state_change.sort(key=lambda x:x.prefix)
	
	return state_change

def state_sql_import(db_login,state_file):
	print('using file '+state_file+' for state file to import')
	state_change=read_state_change_from_file(state_file)
	
	db_handle=pg_connect(db_login)
	
	#for each transition in the state file
	for state_transition in state_change:
		#get the info out of it
		prefix=state_transition.prefix
		suffix=state_transition.suffix
		state_count=state_transition.count
		pg_state_count=0
		
		is_update=False
		
		#see if it already exists in postgres
		success,results=pg_search(db_handle=db_handle,db_login=db_login,prefix=prefix,suffix=suffix)
		if(success):
			#if so, this is an update operation, not an insert
			#and we add the existing count to that from the state file
			is_update=True
			for pg_state_transition in results:
				pg_state_count+=pg_state_transition.count
			state_count+=pg_state_count
		
		if(is_update):
			print('Updating existing transition '+(' '.join(prefix))+' => '+suffix+' to have count '+str(state_count)+' in place of '+str(pg_state_count))
			pg_update(db_handle=db_handle,db_login=db_login,prefix=prefix,suffix=suffix,count=state_count)
		else:
			print('Inserting new transition '+(' '.join(prefix))+' => '+suffix+' with count '+str(state_count))
			pg_insert(db_handle=db_handle,db_login=db_login,prefix=prefix,suffix=suffix,count=state_count)
	
	print('Import completed successfully.')
	db_handle.close()
	return True


if(__name__=='__main__'):
	print('py3_markov version '+VERSION)
	
	run_state_pgsql_import=False
	
	config_file=config.dflt_cfg
	if(len(sys.argv)>1):
		config_file=sys.argv[1]
	print('using JSON config file '+config_file)
	if(len(sys.argv)>2):
		if(sys.argv[2]=='--import-state-file-to-pgsql'):
			run_state_pgsql_import=True
	
	#the state transition array structure,
	#which contains prefixes, suffixes, and probabilities associated with each suffix
	state_change=[]
	
	prefix_len=None
	try:
		prefix_len=int(config.get_json_param(config.read_json_file(config_file),'prefix_len'))
	except ValueError:
		prefix_len=None
	
	if(prefix_len==None):
		prefix_len=2
	prefix=[]
	for i in range(0,prefix_len):
		prefix.append('')
	
	use_pg=config.get_json_param(config.read_json_file(config_file),'use_pg')
	if(use_pg==None):
		use_pg=False
	
	state_file=None
	db_login=None
	if(not use_pg):
		state_file=config.get_json_param(config.read_json_file(config_file),'state_file')
		if(state_file!=None):
			print('using file '+state_file+' for input and output of state_change')
			state_change=read_state_change_from_file(state_file)
		else:
			print('Warn: Not using a state_change file or database backend; memory will not be saved!')
	else:
		#this is for the optional postgres backend
		config_tree=config.read_json_file(config_file)
		pg_user=config.get_json_param(config_tree,'pg_user')
		pg_passwd=config.get_json_param(config_tree,'pg_passwd')
		pg_dbname=config.get_json_param(config_tree,'pg_dbname')
		if(pg_user==None or pg_passwd==None or pg_dbname==None):
			print('Err: Need username, password, and db settings to use postgresql backend')
			use_pg=False
		else:
			db_login=db_info(pg_user,pg_passwd,pg_dbname)
			print('using postgres database '+db_login.db_name+' for input and output of state changes')
	
	if(run_state_pgsql_import):
		print('running state->postgresql db importer...')
		print('if states already exist in postgresql, their counts will be updated based on state file information')
		print('if your state file is too large, this will run out of RAM and crash; sorry!')
		if(not (use_pg)):
			print('Err: use_pg must be true in config for this to work')
			sys.exit(1)
			
		state_file=config.get_json_param(config.read_json_file(config_file),'state_file')
		if(state_file is None):
			print('Err: State file not configured; state file configuration must be present in config')
			sys.exit(1)
		
		state_sql_import(db_login=db_login,state_file=state_file)
		
		sys.exit(0)
	
	print('reading from stdin...')
	
	#first read a string array (of lines) from stdin
	learning_string_lines=[]
	in_line='[]'
	while in_line!='':
		try:
			in_line=input()
			learning_string_lines.append(in_line)
		except EOFError:
			in_line=''
			break
		except UnicodeDecodeError:
			continue
	
	print('learning...')
	
	i=0
	for line in learning_string_lines:
		if(i%10==0):
			print('learning from line index '+str(i)+'...')
		state_change=chain_from(line,state_change,prefix=prefix,use_pg=use_pg,db_login=db_login)
		i+=1
	
	
	if(state_file!=None):
		print('saving updated state_change to '+state_file)
		save_state_change_to_file(state_change,state_file)
	
	print('generating...')
	
	output=generate(state_change,prefix=prefix,use_pg=use_pg,db_login=db_login,back_gen=True)
	
	print('generated output: ')
	
	print(output)
	
	

