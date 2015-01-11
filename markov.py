#!/usr/bin/env python3

import random

#this is just a data structure to store state transition information
#python has no notion of a "struct" so this is as close as we can get
class state_transition:
	def __init__(self,prefix,suffix):
		self.prefix=prefix
		self.suffix=suffix
		self.count=1

VERSION='0.1.0'

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

#add the given text to the chain
#the text follows from the given prefix
#the initial prefix consists of null strings
#the length of the prefix array is used throughout the chain
def chain_from(text,state_change=[],prefix=['',''],verbose_dbg=False):
	token,text=next_token(text)
	
	if(verbose_dbg):
		print('chain_from debug 0, prefix='+str(prefix)+', token='+token)
		print('chain_from debug 1, len(state_change)='+str(len(state_change)))
	
	#if the token was empty, then we hit the end of the text
	#this is the base case to end recursion
	if(token==''):
		return state_change
	
	transition_found=False
	
	#TODO: find possible states with a binary search, since state_change is ordered by prefix
	
	#find the state change entry for our prefix and update it
	for state in state_change:
		if(state.prefix==prefix):
			if(state.suffix==token):
				state.count+=1
				transition_found=True
				break
		#because state_change is sorted by prefix,
		#as soon as we find an entry with a larger prefix,
		#we can stop looking
		elif(state.prefix>prefix):
			break
	
	#if the prefix-suffix combination doesn't exist, then make it now
	if(not transition_found):
		new_state=state_transition(prefix,token)
		
		#insert in order, so we can run faster later by depending on the ordered property
		state_change.append(new_state)
		#note that python's Timsort algorithm makes use of already-sorted sublists,
		#so this should be relatively fast
		state_change.sort(key=lambda x:x.prefix)
		
		"""
		#insert in order, so we can run faster later by depending on the ordered property
		ins_idx=0
		while((ins_idx<len(state_change)) and (new_state.prefix<state_change[ins_idx].prefix)):
			ins_idx+=1
		new_state_change=state_change[0:ins_idx]+[new_state]+state_change[ins_idx:]
		state_change=new_state_change
		"""
		
#		print('chain_from debug 1, new state_change is '+str(state_change))
	
	#update the prefix for the next token
	prefix=[prefix[1],token]
	
	#there may be tokens still left, so try on those
	return chain_from(text,state_change,prefix)

#generate text based on the given state change array
#default prefix of ['',''] generates from starting states
#note that because this is recursive and python doesn't TCO,
#word_limit must be less than max recursion depth
def generate(state_change=[],prefix=['',''],word_limit=40,acc='',verbose_dbg=True):
	#trim leading whitespace just to be pretty
	acc=acc.lstrip(' ')
	
	#if we hit the word limit, return now
	if(word_limit<1):
		return acc
	
	#total count of all states that come from the given prefix
	#this is used so we can calculate probabilities based on state counts
	prefix_count=0
	
	transition_states=[]
	for state in state_change:
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
	
	#no transition state was found (nothing with that prefix),
	#return accumulator now
	if(prefix_count==0):
		return acc
	
	#now make a random number from 0 to prefix_count,
	#to determine which state to transition to
	next_state_idx=random.randint(0,prefix_count-1)
	
	for state in transition_states:
		#we found our next state, so go to it (recursively)
		if(next_state_idx<state.count):
			return generate(state_change,[prefix[1],state.suffix],word_limit-1,acc+' '+state.suffix)
		
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
	
	return acc

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


if(__name__=='__main__'):
	print('py3_markov version '+VERSION)
	
	#the state transition array structure,
	#which contains prefixes, suffixes, and probabilities associated with each suffix
	state_change=[]
	
	prefix_len=2
	prefix=[]
	for i in range(0,prefix_len):
		prefix.append('')
	
	state_file=None
	
	import sys
	if(len(sys.argv)>1):
		state_file=sys.argv[1]
		print('using file '+state_file+' for input and output of state_change')
	
	if(state_file!=None):
		state_change=read_state_change_from_file(state_file)
	
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
	
	print('learning...')
	
	i=0
	for line in learning_string_lines:
		if(i%10==0):
			print('learning from line index '+str(i)+'...')
		state_change=chain_from(line,state_change,prefix=prefix)
		i+=1
	
	
	if(state_file!=None):
		print('saving updated state_change to '+state_file)
		save_state_change_to_file(state_change,state_file)
	
	print('generating...')
	
	output=generate(state_change,prefix=prefix)
	
	print('generated output: ')
	
	print(output)
	
	

