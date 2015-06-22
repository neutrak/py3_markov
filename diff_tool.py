#!/usr/bin/env python3

import os

#a quick difference calculation; this is based on the levenshtein distance
#but is a faster implementation and stores more information
def quick_diff(start_line,end_line):
	#edit distances between each substring pair
	dist=[]
	for i in range(0,len(start_line)+1):
		dist.append([])
		for i in range(0,len(end_line)+1):
			dist[-1].append(0)
	
	#dist is now a len(start_line) by len(end_line) 2d array
	
	#source string -> empty string by delete
	#on each character in source
	for i in range(0,len(start_line)+1):
		dist[i][0]=i
	
	#empty string -> dest string by insert
	#on each character in dest
	for j in range(0,len(end_line)+1):
		dist[0][j]=j
	
	#for each character in target string
	for j in range(1,len(end_line)+1):
		#for each character in source string
		for i in range(1,len(start_line)+1):
			
			#there was a character match
			#so there is no edit distance here
			if(start_line[i-1]==end_line[j-1]):
				#keep edit distance from last entry
				dist[i][j]=dist[i-1][j-1]
			else:
				dist[i][j]=min(
					dist[i-1][j-1]+1,   #sub
					dist[i-1][j]+1,	 #del
					dist[i][j-1]+1	  #ins
					)
	
	return (dist[len(start_line)][len(end_line)],dist)

def get_dictionary(dict_paths=[os.getenv('HOME')+'/words.txt','/usr/dict/words','/usr/share/dict/words'],hard_fail=True):
	import os
	
	path=''
	for dict_path in dict_paths:
		if(os.path.exists(dict_path)):
			path=dict_path
			break
	else:
		print('Error: Could not find a dictionary in the default locations')
		if(hard_fail):
			exit(1)
		return []
	
	fp=open(path,'r')
	words=fp.read().split("\n")
	fp.close()
	
	return words

def similarity_perc(op_cnt,start_line,end_line):
	return (round((1.0-((op_cnt*1.0)/max(len(start_line),len(end_line))))*100.0,2)) if max(len(start_line),len(end_line))>0 else 100

def transpositions(string):
	permutations=[]
	for letter_idx in range(1,len(string)):
		permutations.append(string[0:letter_idx-1]+string[letter_idx]+string[letter_idx-1]+string[letter_idx+1:])
	return permutations

#check a given word against the dictionary
def spellcheck(word,dictionary,max_edit_dist):
	match=False
	for dict_word in dictionary:
		if(word==dict_word):
			match=True
			break
	
	word_transpositions=transpositions(word)
	
	close_words=[]
	if(not match):
		fuzzy_match_words=[]
		transpose_match_words=[]
		for dict_word in dictionary:
			#optimize by skipping words whose length precludes them from a match
			if(abs(len(word)-len(dict_word))>max_edit_dist):
				continue
			
			transpose_match=False
			for chk_word in word_transpositions:
				if(chk_word==dict_word):
					transpose_match_words.append(dict_word)
					transpose_match=True
			
			if(not transpose_match):
				op_cnt=quick_diff(word,dict_word)[0]
				
				#consider a word "close" if the edit distance
				#from the given word to the dictionary word
				#is less than the given max
				if(op_cnt<=max_edit_dist):
					fuzzy_match_words.append(dict_word)
		
		#sort by similarity
		#also alphabetize; note that python's sort is in-place
		fuzzy_match_words.reverse()
		fuzzy_match_words.sort(key=lambda dict_word: similarity_perc(quick_diff(word,dict_word)[0],word,dict_word))
		fuzzy_match_words.reverse()
		
		#combine both transposition matches and fuzzy matches
		#to get an ordered list of all close words
		close_words=transpose_match_words+fuzzy_match_words
	
	return (match,close_words)

if(__name__=='__main__'):
	import sys
	if(len(sys.argv)<3):
		print('Usage: '+sys.argv[0]+' <start line> <end line>')
		exit(1)
	
	start_line=sys.argv[1]
	end_line=sys.argv[2]
	
	edit_dist=quick_diff(start_line,end_line)[0]
	print(str(edit_dist)+' is the edit distance ('+str(similarity_perc(edit_dist,start_line,end_line))+' percent similarity)'+"\n")
	
	print('')
	print('Spellcheck? (y/n)')
	option=input()
	print('got option '+option)
	print('')
	if(option.lower().startswith('y')):
		dictionary=get_dictionary()
		for word in [start_line,end_line]:
			print('Transpositions: '+str(transpositions(word)))
			if(word.find(' ')==-1):
				match,close_words=spellcheck(word,dictionary,1)
				if(match):
					print('CORRECT: '+word)
				else:
					print('INCORRECT: '+word)
				print('close_words='+str(close_words))
			else:
				print('Skipping \"'+word+'\" because it\'s not a word (it contains spaces)')
	

