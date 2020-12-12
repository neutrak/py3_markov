#!/usr/bin/env python3

from py3net import *
import socket
import config
import http_cat
import markov
import random
import rpn
import diff_tool
import sys
import time
import ssl
import json
import errno
import select
import os

#for the database backend which significantly reduces RAM use
use_pg=False
db_login=False
try:
	import postgresql
except ImportError:
	use_pg=False
	db_login=None

SOURCE_CODE_URL='https://github.com/neutrak/py3_markov'
MAX_IRC_LINE_LEN=(512)

#debug state; can be always or never (might get expanded later)
dbg_state='always'
#debug history, how many previously generated debug messages are availabe
dbg_hist=[]
#a max, after which to rotate debug history
dbg_hist_max=3

#NOTE: bot_nick, autojoin_channels, dbg_channels, host, port, ssl, authed_users, and ignored_users
#are specified by the json config file; these are just defaults if values are not configured there

#BEGIN JSON-configurable globals ========================================================

bot_nick='confuseus'
autojoin_channels=[]
dbg_channels=[]
host='ssl.irc.atw-inter.net'
port=6697
use_ssl=True
gen_cmd=True
answer_questions=False
qa_sets=[]

#users allowed to !shup the bot
#(aka clear outgoing queue)
#TODO: if this list is ever used for anything more important, be sure to authenticate in some way, or at least check for channel ops
authed_users=[]

#users to ignore (bots)
#this is a blacklist, like /ignore in many clients
ignored_users=[]

#END JSON-configurable globals ==========================================================

#a list of channels this bot is currently in, which includes user information
#each channel entry is expected to be structured as follows (note that channel names and nicks are globally unique):
#channel: {
# 	names:{
#		nick_a: {
#			mode:'o',
#		},
#		nick_b: {
#			mode:'', #this means the user has no operator status
#		}
# 	}
#	bot_mode:'o', #the bot's own mode, to know whether or not we should ask for ops
#	last_op_rqst:<timestamp>, #the last time the bot asked for ops in this channel
# }
joined_channels={}

#a list of all unit conversions we currently support
#this will be populated as the conversion functions get defined
unit_conv_list=[]

#a class to handle unit conversions in a generic way
#having a seperate case for each was leading to a lot of unnecessary duplication
class unit_conv:
	def __init__(self,dimension,from_abbr,from_disp,to_abbr,to_disp,conv_func):
		self.dimension=dimension
		self.from_abbr=from_abbr
		self.from_disp=from_disp
		self.to_abbr=to_abbr
		self.to_disp=to_disp
		self.conv_func=conv_func
	
	def chk_cmd(self,cmd_esc,cmd):
		#note this is case-insensitive;
		#HOPEFULLY this isn't a problem...
		if((cmd.lower())==(cmd_esc+self.from_abbr+'->'+self.to_abbr)):
			return True
		return False
	
	def output_conv(self,sock,channel,line_post_cmd):
		try:
			from_val=float(line_post_cmd)
			to_val=self.conv_func(from_val)
			py3queueln(sock,'PRIVMSG '+channel+' :'+round_nstr(from_val)+' '+self.from_disp+' is '+round_nstr(to_val)+' '+self.to_disp,1)
		except ValueError:
			py3queueln(sock,'PRIVMSG '+channel+' :Err: '+self.from_abbr+'->'+self.to_abbr+' requires a number, but I couldn\'t find one in your argument',1)

#get a token from the given text, where token ends on the first instance of the substring delimiter
def get_token(text,delimiter):
	success=False
	token=''
	
	delimiter_idx=text.find(delimiter)
	if(delimiter_idx>=0):
		token=text[0:delimiter_idx]
		text=text[delimiter_idx+len(delimiter):]
		success=True
	else:
		token=text
		text=''
		if(len(token)>0):
			success=True
	
	return (success,token,text)


#unit conversion deg F to deg C
def f_to_c(f):
	return (5.0/9.0)*(f-32)

unit_conv_list.append(unit_conv('temperature','f','degrees F','c','degrees C',f_to_c))

#unit conversion deg C to deg F
def c_to_f(c):
	return ((9.0/5.0)*c)+32

unit_conv_list.append(unit_conv('temperature','c','degrees C','f','degrees F',c_to_f))

#unit conversion feet to meters
def ft_to_m(ft):
	return ft*0.3048

unit_conv_list.append(unit_conv('length','ft','feet','m','meters',ft_to_m))

#unit conversion meters to feet
def m_to_ft(m):
	return m*3.281

unit_conv_list.append(unit_conv('length','m','meters','ft','feet',m_to_ft))

#unit conversion feet to centimeters
def ft_to_cm(ft):
	return ft*30.48

unit_conv_list.append(unit_conv('length','ft','feet','cm','centimeters',ft_to_cm))

#unit conversion centimeters to feet
def cm_to_ft(cm):
	return cm*0.03281

unit_conv_list.append(unit_conv('length','cm','centimeters','ft','feet',cm_to_ft))

#unit conversion kilograms to pounds (on earth)
def kg_to_lb(kg):
	return kg*2.205

unit_conv_list.append(unit_conv('mass->force','kg','kilograms','lb','pounds under earth-surface gravity',kg_to_lb))

#unit conversion pounds (on earth) to kilograms
def lb_to_kg(lb):
	return lb*0.4536

unit_conv_list.append(unit_conv('force->mass','lb','pounds under earth-surface gravity','kg','kilograms',lb_to_kg))

#unit conversion miles to kilometers
def mi_to_km(mi):
	return mi*1.609344

unit_conv_list.append(unit_conv('length','mi','miles','km','kilometers',mi_to_km))

#unit conversion kilometers to miles
def km_to_mi(km):
	return km/mi_to_km(1)

unit_conv_list.append(unit_conv('length','km','kilometers','mi','miles',km_to_mi))

#unit conversion inches to centimeters
def in_to_cm(inches):
	return inches*2.54

unit_conv_list.append(unit_conv('length','in','inches','cm','centimeters',in_to_cm))

#unit conversion centimeters to inches
def cm_to_in(cm):
	return cm/in_to_cm(1)

unit_conv_list.append(unit_conv('length','cm','centimeters','in','inches',cm_to_in))

#unit conversion fluid ounces to liters
def oz_to_li(oz):
	return oz*0.02957

unit_conv_list.append(unit_conv('volume','oz','fluid ounces','l','liters',oz_to_li))

#unit conversion liters to fluid ounces
def li_to_oz(li):
	return li/oz_to_li(1)

unit_conv_list.append(unit_conv('volume','l','liters','oz','fluid ounces',li_to_oz))

#determine if the given text is an odd number of question marks
def odd_quest(txt):
	for idx in range(0,len(txt)):
		if(txt[idx]!='?'):
			return False
	if((len(txt)%2)==1):
		return True
	return False

def learn_from(line,state_change,state_file,lines_since_write,lines_since_sort_chk):
	#writing back to the state file and checking the sorting are expensive operations
	#as such, they're not done every line, but only every n lines, as specified here
	
	lines_since_write+=1
	lines_since_sort_chk+=1
	
	check_sorted=False
	if(lines_since_sort_chk>=20):
		check_sorted=True
		lines_since_sort_chk=0
	
	if((line.find('http://')<0) and (line.find('https://')<0)):
		state_change=markov.chain_from(line+"\n",state_change,prefix=['',''],check_sorted=check_sorted,use_pg=use_pg,db_login=db_login)
	else:
		print('Warn: Ignoring line \"'+line+'\" because it contained an http link')
	
	#for postgre writes are done on every line
	if(use_pg):
		lines_since_write=0
	elif(lines_since_write>=60):
		markov.save_state_change_to_file(state_change,state_file)
		lines_since_write=0
	
	return (lines_since_write,lines_since_sort_chk)

def dbg_output(sock,dbg_str):
	global dbg_channels
	global dbg_state
	global dbg_hist
	global dbg_hist_max
	
	if(dbg_str!=''):
		#handle debug string history so users can ask later
		if(len(dbg_hist)>=dbg_hist_max):
			#if we've hit max history, then shift and push out the oldest element
			#note this is sorted from oldest to newest
			dbg_hist=dbg_hist[1:]
#			del(dbg_hist[0])
		#put the new element at the end
		dbg_hist.append(dbg_str)
	
	#if set to, then output to debug channels
	if(dbg_state=='always'):
		for chan in dbg_channels:
			for line in dbg_str.split("\n"):
				if(line!=''):
					py3queueln(sock,'PRIVMSG '+chan+' :'+line[0:MAX_IRC_LINE_LEN-80],4)
					if(len(line[MAX_IRC_LINE_LEN-80:])>0):
						py3queueln(sock,'PRIVMSG '+chan+' :'+line[MAX_IRC_LINE_LEN-80:],4)
#					time.sleep(random.uniform(0.1,1.5))

#this gets the definition of a word out of the given dictionary
def def_word(word,dict_root=os.path.join(os.environ['HOME'],'documents','gcide-0.51')):
	print('Looking up definitions for \''+word+'\'...')
	
	first_char=word[0]
	if(not first_char.isalpha()):
		return (False,'Err: word must start with alphabetical character')
	
	#get the correct dictionary file and slurp it in
	sub_dict_path=os.path.join(dict_root,'CIDE.'+first_char.upper())
	try:
		fp=open(sub_dict_path,'rb')
		fcontent=fp.read().decode('latin-1')
		fp.close()
	except IOError:
		return (False,'Err: could not read dictionary file; is gcide-0.51 installed?')
	except UnicodeDecodeError:
		return (False,'Err: UnicodeDecodeError; your guess is as good as mine, dude')
	
	#check each word in the dictionary file for words which start with this letter
	#as we find entry blocks for this word, add them to the list for further parsing
	definitions=[]
	found_word=False
	entry_blocks=[]
	for line in fcontent.split("\n"):
		#if we found the word then just continue to get the whole block
		if(found_word):
			if(line==''):
				#this supports multiple entry blocks for the same word
				#(a break would only support one block, and hence one definition)
				found_word=False
			entry_blocks[len(entry_blocks)-1]+="\n"+line
		#check each entry for the word we're trying to define
		elif(line.startswith('<p><ent>')):
			ent_word=line[len('<p><ent>'):line.find('</ent>')]
			#if we found a definition for this word, then store the block
			#note this is case-sensitive
			if(ent_word==word):
				found_word=True
				print('Dbg: found word '+ent_word)
				entry_blocks.append(line)
	
	print('')
	
	#for each entry block, strip out the definition and anything else we may want
	#and discard the rest
	for entry_block in entry_blocks:
		entry_block=entry_block.strip("\n")
		entry_block=entry_block.replace('<br/','')
		print(entry_block+"\n")
		
		try:
			def_entry=entry_block[entry_block.find('<def>'):entry_block.find('</def>')]
		except:
			continue
		def_entries=[http_cat.html_strip_tags(def_entry)]
		
		#TODO: support parts of speech, other information about this word
		
		definitions+=def_entries
	
	#if no definitions were found, try again with an upper-case first letter,
	#or, if the first letter was already upper-case, return error
	if(len(definitions)==0):
		if(first_char==first_char.lower()):
			return def_word(first_char.upper()+word[1:],dict_root)
		return (False,'Err: no definition found')
	#one or more definitions was found, return success and the definitions
	return (True,definitions)

#round so numbers look nice on IRC
def round_nstr(num):
	return ('%10.5f' % num).lstrip(' ')

#do substitutions which people expect from IRC but are really client-side
def irc_str_map(line_post_cmd):
	if(line_post_cmd.startswith('/me')):
		line_post_cmd='\x01ACTION'+line_post_cmd[len('/me'):]
	return line_post_cmd

#handle conversions (stored in a generic unit_conv list)
def handle_conversion(sock,cmd_esc,cmd,line_post_cmd,channel):
	global unit_conv_list
	handled=False
	
	for conversion in unit_conv_list:
		if(conversion.chk_cmd(cmd_esc,cmd)):
			conversion.output_conv(sock,channel,line_post_cmd)
			handled=True
	
	return handled

#handle an omdb command
def handle_omdb(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm):
	if(line_post_cmd!=''):
		title_words=line_post_cmd.rstrip(' ').split(' ')
		for i in range(0,len(title_words)):
			if(title_words[i][0]==title_words[i][0].lower()):
				title_words[i]=title_words[i][0].upper()+title_words[i][1:]
		url='http://www.omdbapi.com/?t='+('+'.join(title_words))+'&y=&plot=short&r=json'
		try:
			response=http_cat.get_page(url)
		except:
			py3queueln(sock,'PRIVMSG '+channel+' :Err: Could not retrieve data (weird characters in title?)',1)
			return
		
		response_type=response[0].split("\n")[0].rstrip("\r")
		if(response_type.find('200 OK')<0):
			py3queueln(sock,'PRIVMSG '+channel+' :Err: \"'+response_type+'\"',1)
		else:
			try:
				json_tree=json.loads(response[1])
			except ValueError:
				py3queueln(sock,'PRIVMSG '+channel+' :Err: Could not parse json response from omdb',1)
				return
			
			#movie information now that retrieval is done
			title=config.get_json_param(json_tree,'Title')
			title='' if title==None else title
			rating=config.get_json_param(json_tree,'imdbRating')
			rating='' if rating==None else rating
			year=config.get_json_param(json_tree,'Year')
			year='' if year==None else year
			#remove unicode to be IRC-friendly
			year=year.replace('–','-')
			genre=config.get_json_param(json_tree,'Genre')
			genre='' if genre==None else genre
			plot=config.get_json_param(json_tree,'Plot')
			plot='' if plot==None else plot
			
			if((title=='') and (rating=='') and (year=='') and (genre=='') and (plot=='')):
				py3queueln(sock,'PRIVMSG '+channel+' :Err: No information (movie might not be in omdb, or might not exist)',1)
			else:
				py3queueln(sock,'PRIVMSG '+channel+' :'+title+' / '+rating+' / '+year+' / '+genre+' / '+plot,1)
	else:
		py3queueln(sock,'PRIVMSG '+channel+' :Err: omdb requires a movie title as a parameter',1)


#handle a spellcheck command
def handle_spellcheck(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm):
	dictionary=diff_tool.get_dictionary(hard_fail=False)
	
	#by default a word is close if it is one or fewer edits away from the given word
	edit_distance=1
	chk_words=line_post_cmd.split(' ')
	
	#if requested, use a user-given edit distance to allow for more word suggestions
	#custom edit distance is the /last/ space-delimited argument
	#(multiple words may be given before it)
	if(len(chk_words)>1 and chk_words[-1].isdigit()):
		edit_distance=int(chk_words[-1])
		chk_words=chk_words[0:len(chk_words)-1]
	
	#limit edit distance to <=5 though,
	#so we don't time out or get words that don't make any sense
	edit_distance=min(edit_distance,5)
	
	#how many words we can be requested to spell in a single call
	#words after this limit will be ignored
	max_words_per_line=2
	
	words_on_line=0
	for chk_word in chk_words:
		#skip words after the max
		if(words_on_line>=max_words_per_line):
			break
		
		#check this word; spellcheck uses a edit distance based fuzzy match internally
		#note that transpositions are included as a special case within the spellcheck function
		spellcheck_output=''
		match,close_words=diff_tool.spellcheck(chk_word,dictionary,edit_distance)
		if(match):
			spellcheck_output+='CORRECT: \''+chk_word+'\' is in my dictionary'
		else:
			spellcheck_output+='INCORRECT: \''+chk_word+'\' is NOT in my dictionary'
			if(len(close_words)>0):
				spellcheck_output+='; you may mean: '
			
			print('[dbg] for \''+chk_word+'\': close_words='+str(close_words))
			
			max_fix_words=8
			fix_word_cnt=0
			for fix_word in close_words:
				if(fix_word_cnt>=max_fix_words):
					break
				
				if(fix_word_cnt!=0):
					spellcheck_output+=', '
				spellcheck_output+=fix_word
				fix_word_cnt+=1
			
			if(fix_word_cnt>=max_fix_words):
				spellcheck_output+=', ...'
		
		py3queueln(sock,'PRIVMSG '+channel+' :'+spellcheck_output,1)
		
		words_on_line+=1

def handle_timecalc(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm):
	arguments=line_post_cmd.split(' ')
	if(len(arguments)<3):
		py3queueln(sock,'PRIVMSG '+channel+' :Err: Too few arguments given to '+cmd_esc+'timecalc command; Usage: '+cmd_esc+'timecalc <%R> <tz1> <tz2>',1)
		return
	
	#parse out %R
	#%R means <hours (0-23)>:<minutes (0-60)>
	
	#the time is valid until we're missing something we need or an exception is thrown
	valid_time=True
	time_str=arguments[0]
	time_list=time_str.split(':')
	
	#note that we use < instead of != because if seconds are given that's okay we just ignore them
	if(len(time_list)<2):
		valid_time=False
	
	hours=0
	minutes=0
	try:
		hours=int(time_list[0])
		minutes=int(time_list[1])
	except ValueError:
		valid_time=False
	
	#note that leap seconds can cause a valid 23:60 time, but we don't consider that
	if(hours<0 or hours>=24 or minutes<0 or minutes>=60):
		valid_time=False
	
	if(not valid_time):
		py3queueln(sock,'PRIVMSG '+channel+' :Err: Invalid time given; syntax is <hours>:<minutes> where 0<=hours<=23, 0<=minutes<=59',1)
		return
	
	#save off the given time so we can manipulate the hours and minutes to calculate for the second timezone
	#this is what the time is in the first timezone
	given_hours=hours
	given_minutes=minutes
	
	#now get the timezones from the remaining arguments
	#(which we know exist because we did a check earlier)
	tz_1_str=arguments[1]
	tz_2_str=arguments[2]
	
	#these are utc offsets
	tz_1=0
	tz_2=0
	
	try:
		tz_1=int(tz_1_str)
		tz_2=int(tz_2_str)
	except ValueError:
		#note we re-use the valid_time variable here
		#in order to save memory, and since if it was previously false we would have already returned
		valid_time=False
	
	if(not valid_time):
		py3queueln(sock,'PRIVMSG '+channel+' :Err: Invalid timezone(s) given; should be an integer value representing UTC offset',1)
		return
	
	#if we got here then we have a valid time, and 2 valid timezones
	#time to do the real calculation!
	tz_diff=(tz_2-tz_1)
	hours+=tz_diff
	
	#calculate carry (for when someone is a day different due to clock rollover)
	day_diff=0
	if(hours>23):
		hours-=24
		day_diff=1
	elif(hours<0):
		hours+=24
		day_diff=-1
	
	#pretty formatting by prepending 0s when numbers are <10
	given_hours_str=str(given_hours)
	if(len(given_hours_str)<2):
		given_hours_str='0'+given_hours_str
	given_minutes_str=str(given_minutes)
	if(len(given_minutes_str)<2):
		given_minutes_str='0'+given_minutes_str
	hours_str=str(hours)
	if(len(hours_str)<2):
		hours_str='0'+hours_str
	minutes_str=str(minutes)
	if(len(minutes_str)<2):
		minutes_str='0'+minutes_str
	
	py3queueln(sock,'PRIVMSG '+channel+' :'+given_hours_str+':'+given_minutes_str+' at UTC '+tz_1_str+' is '+hours_str+':'+minutes_str+(' the next day' if day_diff>0 else (' the previous day' if day_diff<0 else ''))+' at UTC '+tz_2_str,1)

def handle_wiki(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm):
	#TODO: handle more specific errors; this is super nasty but should keep the bot from crashing
	try:
		wiki_search=line_post_cmd.replace(' ','%20')
		wiki_url='https://en.wikipedia.org/w/api.php?action=opensearch&format=json&search='+wiki_search+'&limit=2&namespace=0'
#			response=http_cat.get_page(wiki_url)
		#HTTPS generally uses port 443, rather than port 80
		response=http_cat.get_page(wiki_url,443)
		
		response_type=response[0].split("\n")[0].rstrip("\r")
		
		#if we get a 301 moved and the page requested was lower case then
		#before giving up try it as upper-case
		if((response_type.find('301 Moved')>=0) and (line_post_cmd[0]==line_post_cmd[0].lower())):
			return handle_bot_cmd(sock,cmd_esc,
				cmd,
				(line_post_cmd[0].upper())+(line_post_cmd[1:]),
				channel,
				nick,is_pm,state_change,use_pg,db_login)
		
		if(response_type.find('200 OK')<0):
			py3queueln(sock,'PRIVMSG '+channel+' :Err: \"'+response_type+'\"',1)
		else:
			wiki_text=response[1]
			if(wiki_text==''):
				py3queueln(sock,'PRIVMSG '+channel+' :Err: wiki got null page text',1)
			else:
				print(wiki_text) #debug
				
				#parse JSON and output the juicy bits
				wiki_json=json.loads(wiki_text)
				
				#disambiguate?
				valid_output=True
				if(len(wiki_json[1])>1):
					for n in range(0,len(wiki_json[1])):
						if(wiki_json[1][n].lower()==line_post_cmd.lower()):
							break
					else:
						py3queueln(sock,'PRIVMSG '+channel+' :Please disambiguate; you may want one of the following: '+', '.join(wiki_json[1]))
						valid_output=False
				
				if(len(wiki_json[3])==0):
					py3queueln(sock,'PRIVMSG '+channel+' :Err: No wikipedia pages found for \"'+line_post_cmd+'\"')
					valid_output=False
				
				if(valid_output):
					output_text=' '.join(wiki_json[2])
					reserved_len=len('PRIVMSG '+channel+' :...'+"\r\n")
					if(len(output_text)>=(MAX_IRC_LINE_LEN-reserved_len)):
#						output_text=output_text[0:(MAX_IRC_LINE_LEN-reserved_len)]+'...'
						output_text=output_text[0:MAX_IRC_LINE_LEN]+'...'
					py3queueln(sock,'PRIVMSG '+channel+' :'+output_text,1)
					
					#link the wiki page itself?
					py3queueln(sock,'PRIVMSG '+channel+' :'+' '.join(wiki_json[3]),1)
	except:
		py3queueln(sock,'PRIVMSG '+channel+' :Err: wiki failed to get page text',1)

def handle_define(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm):
	#what's the word, dawg?
	word=line_post_cmd
	
	#get all the definitions of the word from the local dictionary
	success,definitions=def_word(word)
	
	#if definitions were found, then output those
	if(success):
		def_line=word+': '
		for i in range(0,len(definitions)):
			if(i!=0):
				def_line+=' | '
			def_line+='('+str(i)+') '+definitions[i]
		
		py3queueln(sock,'PRIVMSG '+channel+' :'+def_line[0:MAX_IRC_LINE_LEN])
	#no definitions found; output the error message
	else:
		err_msg=definitions
		py3queueln(sock,'PRIVMSG '+channel+' :'+err_msg)

#display an example of the given command
def handle_example(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,state_change,use_pg,db_login):
	if(line_post_cmd==''):
		py3queueln(sock,'PRIVMSG '+channel+' :Err: Missing argument (the command); see '+cmd_esc+'help for a command list',1)
	elif(line_post_cmd==(cmd_esc+'wut')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wut',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'wut','',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'example')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'example '+cmd_esc+'wut',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'example',cmd_esc+'wut',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'dbg')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'dbg',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'dbg','',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'shup')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'shup 4',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'shup','4',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'calc')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'calc 10*9^-3',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'calc','10*9^-3',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'wiki')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wiki wikipedia',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'wiki','wikipedia',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'define')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'define dictionary',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'define','dictionary',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'omdb')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'omdb Airplane!',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'omdb','Airplane!',channel,nick,is_pm,state_change,use_pg,db_login)
	elif((line_post_cmd==(cmd_esc+'splchk')) or (line_post_cmd==(cmd_esc+'sp')) or (line_post_cmd==(cmd_esc+'spellcheck'))):
		#intentional misspelling to demonstrate spellcheck ability
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'splchk misspeling',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'splchk','misspeling',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'dieroll')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'dieroll 6',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'dieroll','6',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'time')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'time -6',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'time','-6',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'timecalc')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'timecalc 12:00 -6 +0',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'timecalc','12:00 -6 +0',channel,nick,is_pm,state_change,use_pg,db_login)
	#TODO: replace seen-quit with just seen once we have a working user list for every channel
	elif(line_post_cmd==(cmd_esc+'seen-quit')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'seen-quit neutrak',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'seen-quit','neutrak',channel,nick,is_pm,state_change,use_pg,db_login)
	elif(line_post_cmd==(cmd_esc+'oplist')):
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'oplist add neutrak',1)
		handle_bot_cmd(sock,cmd_esc,cmd_esc+'oplist','add neutrak',channel,nick,is_pm,state_change,use_pg,db_login)
	elif((line_post_cmd==(cmd_esc+'login')) or (line_post_cmd==(cmd_esc+'setpass'))):
		py3queueln(sock,'PRIVMSG '+channel+' :Warn: command '+line_post_cmd+' is only valid in PM and contains sensitive information, so it does not have an example listed here',1)
	elif((line_post_cmd==(cmd_esc+'help')) or (line_post_cmd==(cmd_esc+'part')) or (line_post_cmd==(cmd_esc+'source'))):
		py3queueln(sock,'PRIVMSG '+channel+' :Warn: '+line_post_cmd+' takes no arguments and so has no examples; see '+cmd_esc+'help for information about it',1)
	else:
		for conversion in unit_conv_list:
			conv_cmd=(cmd_esc+conversion.from_abbr+'->'+conversion.to_abbr)
			if(line_post_cmd==conv_cmd):
				py3queueln(sock,'PRIVMSG '+channel+' :'+conv_cmd+' 1',1)
				handle_bot_cmd(sock,cmd_esc,conv_cmd,'1',channel,nick,is_pm,state_change,use_pg,db_login)
				break
		else:
			py3queueln(sock,'PRIVMSG '+channel+' :Err: Unrecognized argument ('+line_post_cmd+'); see '+cmd_esc+'help for a command list',1)

def handle_help(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm):
	global unit_conv_list
	
	if(is_pm):
		py3queueln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wut                          -> generate text based on markov chains',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'example <command>            -> display an example of a command and its output',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'dbg <always|never|#>         -> enable/disable/show debug info about markov text generation (authorized uses can enable or disable, any users can get history)',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'help                         -> displays this command list',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'shup [min nice lvl]          -> clears low-priority messages from sending queue (authorized users can clear higher priority messages)',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'part                         -> parts current channel (you can invite to me get back)',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'calc <expression>            -> simple calculator; supports +,-,*,/,and ^; uses rpn internally',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wiki <topic>                 -> grabs topic summary from wikipedia',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'define <word>                -> checks definintion of word in gcide dictionary',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'source                       -> links the github url for this bot\'s source code',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'omdb <movie name>            -> grabs movie information from the open movie database',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'splchk <word> [edit dist]    -> checks given word against a dictionary and suggests fixes',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'dieroll [sides]              -> generates random number in range [1,sides]',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'time [utc offset tz]         -> tells current UTC time, or if a timezone is given, current time in that timezone',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'timecalc <%R> <tz1> <tz2>    -> tells what the given time (%R == hours:minutes on a 24-hour clock) at the first utc-offset timezone will be at the second utc-offset timezone',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'seen-quit <nick>             -> checks log files for last time when given nick was seen quitting (does NOT check if they\'re currently here)',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'oplist <add|rm|check> <user> -> allows channel operators to authorize/register other channel operators in a way that will persist between reconnections',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'login <pass> [channel]       -> [PM ONLY] if you are an authorized channel operator, logs you in to that channel',3)
		py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'setpass <pass> [oldpass]     -> [PM ONLY] sets a passphrase for your channel operator account, if you have been invited to become a channel operator; if you have already set a passphrase oldpass is required for authorization',3)
		for conversion in unit_conv_list:
			help_str='PRIVMSG '+channel+' :'+cmd_esc+conversion.from_abbr+'->'+conversion.to_abbr+' <value>'
			while(len(help_str)<len('PRIVMSG '+channel+' :'+cmd_esc+'XXXXXXXXXXXXXXXXXXXXXXXXXXXXX')):
				help_str+=' '
			help_str+='-> converts '+conversion.dimension+' from '+conversion.from_disp+' to '+conversion.to_disp
			py3queueln(sock,help_str,3)
	else:
		py3queueln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot; use '+cmd_esc+'wut or address me by name to generate text; PM !help for more detailed help',3)
			

#check when a user was last seen
def handle_seen(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm,log_file='log.txt'):
	import datetime
	
	#read the last 5000 lines (or more if they're short)
	backlog_chars=(512*5000)
	#or the whole file, if it's smaller than that
	file_size=os.path.getsize(log_file)
	
	fp=open(log_file,'r')
	fp.seek(0,os.SEEK_END)
	fp.seek(file_size-min(file_size,backlog_chars))
	fcontent=fp.read()
	fp.close()
	
	#start at the first complete line
	#no partial line parsing
	nl_idx=fcontent.find("\n")
	if(nl_idx>=0):
		fcontent=fcontent[nl_idx+1:]
	
	#time the user was last seen, as a *nix timestamp string
	last_seen_time='0'
	
	#look for QUIT lines with the following format
	#1467596281 :BasmatiRice!uid32945@2604:8300:100:200b:6667:2:0:80b1 QUIT :"Connection closed for inactivity"
	for line in fcontent.split("\n"):
		sp_idx=line.find(' ')
		if(sp_idx<0):
			continue
		
		#store timestamp so we can say when the user quit
		timestamp=line[0:sp_idx]
		line=line[sp_idx+1:]
		
		#skip PRIVMSG, PING, etc.
		if(not line.startswith(':')):
			continue
		
		#get the nick that quit
		line=line[1:]
		bang_idx=line.find('!')
		if(bang_idx<0 or bang_idx>30):
			continue
		nick=line[0:bang_idx]
		line=line[bang_idx+1:]
		
		#if this isn't who we were looking for then skip it
		if(nick.lower()!=line_post_cmd.lower()):
			continue
		
		sp_idx=line.find(' ')
		if(sp_idx>=0 and line[sp_idx+1:].startswith('QUIT')):
			print('[dbg] '+timestamp+' :'+line)
			last_seen_time=timestamp
		#if this wasn't a quit ignore it
	
	if(last_seen_time=='0'):
		py3queueln(sock,'PRIVMSG '+channel+' :Warn: I don\'t have any recent QUITs from nick '+line_post_cmd+' in my logs; I might not have been there; they might not have existed; no idea, man',3)
	else:
		pretty_time=datetime.datetime.utcfromtimestamp(int(last_seen_time)).strftime('%Y-%m-%d %H:%M:%S UTC')
		py3queueln(sock,'PRIVMSG '+channel+' :Nick '+line_post_cmd+' was last seen quitting a channel I was in at '+pretty_time+' ('+last_seen_time+'); check if they\'re here now; I don\'t do that',3)


def require_pg(sock,cmd_esc,cmd,channel):
	if(not use_pg):
		py3queueln(sock,'PRIVMSG '+channel+' :Err: '+cmd_esc+cmd+' is only valid if a postgres database is in use; ask the bot operator to fix the configuration to allow this command to be used',1)
		return False
	return True

def handle_oplist(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,use_pg,db_login):
	if(not require_pg(sock,cmd_esc,cmd,channel)):
		return
	
#	if(not (is_channel_operator(channel,nick))):
#		py3queueln(sock,'PRIVMSG '+channel+' :Err: '+cmd_esc+'oplist can only be used by channel operators; come back when you have ops',1)
#		return
	
	args=line_post_cmd.split(' ')
	
	if(len(args)<2):
		py3queueln(sock,'PRIVMSG '+channel+' :Usage: '+cmd_esc+'oplist <add|rm|check> <user>',1)
		return
	
	py3queueln(sock,'PRIVMSG '+channel+' :Err: '+cmd_esc+'oplist command has not yet been implemented; check back soon',1)
	return
	
	if(args[0]=='add'):
		#TODO: if this user is already authorized for this channel, just say so and return
		#TODO: if this user is not yet authorized for this channel but exists in the oplist_users table,
		#then add an associated entry for oplist_channels
		#and grant them ops now
		#TODO: if this user is not authorized and has never been authorized before,
		#delete any existing database oplist_users entries for this user where passphrase is null in case they were previously invited and didn't complete signup
		#and create a new database entry with their current hostmask used to idenitfy them and null passphrase
		return
	elif(args[0]=='rm'):
		#TODO: if the user currently has channel ops, de-op them
		#TODO: remove the specified users from the list of channel operators for this channel
		return
	elif(args[0]=='check'):
		#TODO: output the list of channels this user is authorized for
		return

def handle_login(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,use_pg,db_login):
	if(not require_pg(sock,cmd_esc,cmd,channel)):
		return
	
	if(not is_pm):
		py3queueln(sock,'PRIVMSG '+channel+' :Err: '+cmd_esc+'login is only valid in PM; you should change your passphrase IMMEDIATELY with '+cmd_esc+'setpass',1)
		return
	
	#TODO: write this
	py3queueln(sock,'PRIVMSG '+channel+' :Err: '+cmd_esc+'login command has not yet been implemented; check back soon',1)
	return

def handle_setpass(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,use_pg,db_login):
	if(not require_pg(sock,cmd_esc,cmd,channel)):
		return
	
	if(not is_pm):
		py3queueln(sock,'PRIVMSG '+channel+' :Err: '+cmd_esc+'setpass is only valid in PM (and use a different passphrase from the one you just posted in the channel...)',1)
		return
	
	#TODO: write this
	py3queueln(sock,'PRIVMSG '+channel+' :Err: '+cmd_esc+'setpass command has not yet been implemented; check back soon',1)
	return


def handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,state_change,use_pg,db_login):
	global gen_cmd
	global unit_conv_list
	global dbg_channels
	global dbg_state
	global dbg_hist
	global dbg_hist_max
	global qa_sets
	handled=False
	
	dbg_str=''
	
	#check if this was a bot command
	if((cmd==(cmd_esc+'wut')) or (cmd==cmd_esc)):
		output=''
		if(line_post_cmd!=''):
			output,dbg_str=markov.gen_from_str(state_change,use_pg,db_login,irc_str_map(line_post_cmd),random.randint(0,1)+1,retries_left=3,qa_sets=qa_sets)
		if(output==''):
			output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
		
		#properly close CTCP when it's generated
		if(output.startswith('\x01ACTION') and (not output.endswith('\x01'))):
			output+='\x01'
		
		#prevent generating commands directed towards other bots,
		#if configured to do that
		if(not gen_cmd):
			if(output.startswith('!')):
				output='\\'+output
		
		py3queueln(sock,'PRIVMSG '+channel+' :'+output,1)
#		dbg_str='[dbg] generated from line \"'+line_post_cmd+'\"'+"\n"+dbg_str
		dbg_str='[dbg] (\"'+line_post_cmd+'\") '+dbg_str
		handled=True
	elif(cmd==(cmd_esc+'example')):
		handle_example(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,state_change,use_pg,db_login)
		handled=True
	elif(cmd==(cmd_esc+'dbg') or cmd==(cmd_esc+'debug')):
		#set debug channel ON if authorized
		if(line_post_cmd=='always'):
			if(nick in authed_users):
				dbg_state='always'
				py3queueln(sock,'PRIVMSG '+channel+' :Info: Now outputting debug messages in '+(','.join(dbg_channels))+' without being asked',1)
			else:
				py3queueln(sock,'PRIVMSG '+channel+' :Err: You are not authorized to change debug settings',1)
		#set debug channel OFF if authorized
		elif(line_post_cmd=='never'):
			if(nick in authed_users):
				dbg_state='never'
				py3queueln(sock,'PRIVMSG '+channel+' :Info: No longer outputting debug messages without being asked',1)
			else:
				py3queueln(sock,'PRIVMSG '+channel+' :Err: You are not authorized to change debug settings',1)
		#no argument or an index means display some debug info from the history
		elif(line_post_cmd.strip()=='' or line_post_cmd.isdigit()):
			#print the entire debug history to the console a line at a time
			for hist in dbg_hist:
				print(hist)
			
			#digits are reverse indices into the debug history
			hist_ofst=0
			if(line_post_cmd.isdigit()):
				hist_ofst=int(line_post_cmd)
			#bounds checking for security and to prevent crashing
			if(hist_ofst<0 or hist_ofst>=len(dbg_hist)):
				hist_ofst=0
				py3queueln(sock,'PRIVMSG '+channel+' :Warn: Invalid history offset; displaying last debug value',1)
			
			#if no argument is given then assume the user wanted the last debug message
			if(len(dbg_hist)>0):
#				py3queueln(sock,'PRIVMSG '+channel+' :'+dbg_hist[len(dbg_hist)-1-hist_ofst],2)
				line=dbg_hist[len(dbg_hist)-1-hist_ofst]
				py3queueln(sock,'PRIVMSG '+channel+' :'+line[0:MAX_IRC_LINE_LEN-80],2)
				if(len(line[MAX_IRC_LINE_LEN-80:])>0):
					py3queueln(sock,'PRIVMSG '+channel+' :'+line[MAX_IRC_LINE_LEN-80:],2)
			else:
				py3queueln(sock,'PRIVMSG '+channel+' :Err: No debug history exists',1)
		else:
			py3queueln(sock,'PRIVMSG '+channel+' :Err: Unrecognized argument given to dbg, \''+line_post_cmd+'\'',1)
		handled=True
	elif(cmd==(cmd_esc+'help')):
		handle_help(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	#clear (low-priority) messages from the output queue
	elif((cmd==(cmd_esc+'shup')) or (cmd==(cmd_esc+'shoo'))):
		#the minimum nice value to clear messages from the output queue
		nice_lvl=4
		try:
			nice_lvl=int(line_post_cmd.strip(' '))
		except ValueError:
			nice_lvl=4
		
		#authorized users can suppress high-priority output
		if(nick in authed_users):
			nice_lvl=max(nice_lvl,1)
		#unauthorized users can only suppress low-priority output
		else:
			nice_lvl=max(nice_lvl,4)
		
		py3clearq(nice_lvl)
		py3queueln(sock,'PRIVMSG '+channel+' :Info: outgoing message queue cleared of low-priority messages (nice_lvl='+str(nice_lvl)+')',1)
		handled=True
	elif(cmd==(cmd_esc+'part')):
		if(not is_pm):
			py3queueln(sock,'PART '+channel+' :Goodbye for now (you can invite me back any time)',1)
		else:
			py3queueln(sock,'PRIVMSG '+channel+' :part from where, asshole? this is a PM!',1)
		handled=True
	#conversions are their own function now
	elif(handle_conversion(sock,cmd_esc,cmd,line_post_cmd,channel)):
		handled=True
	elif(cmd==(cmd_esc+'calc')):
		try:
			err_msgs,result=rpn.rpn_eval(rpn.rpn_translate(line_post_cmd))
			if(len(result)==1):
				py3queueln(sock,'PRIVMSG '+channel+' :'+str(result[0]),1)
			else:
				py3queueln(sock,'PRIVMSG '+channel+' :Warn: An error occurred during evaluation; simplified RPN expression is '+str(result),1)
				for err_idx in range(0,len(err_msgs)):
					py3queueln(sock,'PRIVMSG '+channel+' :Err #'+str(err_idx)+': '+str(err_msgs[err_idx]),3)
		except ValueError:
			py3queueln(sock,'PRIVMSG '+channel+' :Err: Could not parse expression (ValueError) (divide by zero?)',1)
		except IndexError:
			py3queueln(sock,'PRIVMSG '+channel+' :Err: Could not parse expression (IndexError) (mismatched parens?)',1)
		except:
			py3queueln(sock,'PRIVMSG '+channel+' :Err: Unhandled exception in rpn parsing; tell neutrak the command you used to get this and he\'ll look into it',1)
		handled=True
	elif(cmd==(cmd_esc+'wiki')):
		handle_wiki(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	#add wiktionary or some other dictionary with definitions if at all reasonable to do
	#(we're using gcide)
	elif(cmd==(cmd_esc+'define')):
		handle_define(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	elif(cmd==(cmd_esc+'source')):
		py3queueln(sock,'PRIVMSG '+channel+' :bot source code: '+SOURCE_CODE_URL,1)
		handled=True
	elif((cmd==(cmd_esc+'omdb')) or (cmd==(cmd_esc+'imdb'))):
		handle_omdb(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	elif((cmd==(cmd_esc+'splchk')) or (cmd==(cmd_esc+'spellcheck')) or (cmd==(cmd_esc+'sp')) or (cmd==(cmd_esc+'spell'))):
		handle_spellcheck(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	elif(cmd==(cmd_esc+'dieroll')):
		sides=6
		if(line_post_cmd!=''):
			try:
				sides=int(line_post_cmd)
			except ValueError:
				py3queueln(sock,'PRIVMSG '+channel+' :Warn: Invalid number of sides, assuming d-6',1)
				sides=6
		if(sides<1):
			py3queueln(sock,'PRIVMSG '+channel+' :Warn: Number of sides less than 1, setting number of sides 1 (this will return 1)',1)
			sides=1
		
		value=random.randint(1,sides)
		py3queueln(sock,'PRIVMSG '+channel+' :Rolled a '+str(value)+' with a d'+str(sides),1)
		
		handled=True
	elif(cmd==(cmd_esc+'time')):
		tz=0
		if(line_post_cmd!=''):
			try:
				tz=float(line_post_cmd)
			except ValueError:
				py3queueln(sock,'PRIVMSG '+channel+' :Err: '+line_post_cmd+' is not a valid UTC-offset timezone; will give UTC time instead...',1)
		if(abs(tz)>24):
			py3queueln(sock,'PRIVMSG '+channel+' :Err: timezone offsets from utc cannot be outside the range [-24,24] because that makes no sense; giving UTC time...')
			tz=0
		current_time=time.asctime(time.gmtime(time.time()+(tz*60*60)))
		py3queueln(sock,'PRIVMSG '+channel+' :Current time is '+current_time+' (UTC '+('+'+str(tz) if tz>=0 else str(tz))+')')
		handled=True
	elif(cmd==(cmd_esc+'timecalc')):
		handle_timecalc(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	#TODO: add weather forecast via darksky or yahoo weather or http://weather.gc.ca/canada_e.html (for Canada)
	elif(cmd==(cmd_esc+'seen-quit')):
		handle_seen(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	elif(cmd==(cmd_esc+'oplist')):
		handle_oplist(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,use_pg,db_login)
		handled=True
	#login (op aliased) -> grant the user the appropriate mode on all channels they are authorized for, or a specific channel if a channel was specified
	elif((cmd==(cmd_esc+'login')) or (cmd==(cmd_esc+'op'))):
		handle_login(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,use_pg,db_login)
		handled=True
	#setpass -> register a user who has a nick and hostmask that was invited by someone using !oplist add
	elif(cmd==(cmd_esc+'setpass')):
		handle_setpass(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,use_pg,db_login)
		handled=True
	elif(cmd.startswith(cmd_esc)):
		try:
			#alternate conversion syntax
			#check if the "command" is a valid floating point number
			conv_arg=float(cmd[len(cmd_esc):])
			
			#the line after the "command" is the command checked against the conversion list
			#some arguments here are a little weird because they're being transposed
			found_conversion=False
			for conversion in unit_conv_list:
				#we found the requested conversion, so do the thing and output the result
				#note that "X to Y" gets translated here as "X->Y"
				if(conversion.chk_cmd(cmd_esc,cmd_esc+line_post_cmd.replace(' to ','->'))):
					conversion.output_conv(sock,channel,conv_arg)
					found_conversion=True
			
			#this was a valid number, but something went wrong during conversion
			if(not found_conversion):
				py3queueln(sock,'PRIVMSG '+channel+' :Err: Conversion not found '+line_post_cmd,1)
			
			#in any case if we got a number don't handle this line any more
			handled=True
		#the "command" wasn't a valid floating point number,
		#so output an error for PM, or just do nothing in a channel
		except ValueError:
			if(is_pm):
				py3queueln(sock,'PRIVMSG '+channel+' :Warn: Invalid command: \"'+cmd+'\"; see '+cmd_esc+'help for help',1)
		
		#this prevents the bot from learning from unrecognized ! commands
		#(which are usually meant for another bot)
#		handled=True

	return (handled,dbg_str)


def handle_privmsg(sock,line,state_change,state_file,lines_since_write,lines_since_sort_chk):
	global gen_cmd
	global qa_sets
	
	#get some information (user, nick, host, etc.)
	success,info,line=get_token(line,' ')
	info=info.lstrip(':')
	success,nick,info=get_token(info,'!')
	success,realname,info=get_token(info,'@')
	success,hostmask,info=get_token(info,' ')
	success,privmsg_cmd,line=get_token(line,' ')
	success,channel,line=get_token(line,' ')
	
	line=line.lstrip(':')
	
	#debug
	log_line('['+channel+'] <'+nick+'> '+line)
	
	#ignore blacklisted users,
	#but throw some output on the console so we know that's happening
	if nick in ignored_users:
		print('Warn: ignored line from '+nick+' because their nick is blacklisted (ignored)')
		return (lines_since_write,lines_since_sort_chk)
	
	#strip trailing whitespace because users expect that to not matter
	line=line.rstrip(' ').rstrip("\t")
	
	#and now because whitespace is gone it's possible to have a blank line
	#so ignore blank lines
	if(line==''):
		return (lines_since_write,lines_since_sort_chk)
	
	#if they PM'd us, then PM 'em right back
	#that'll show 'em
	is_pm=False
	if(channel==bot_nick):
		is_pm=True
		channel=nick
	
	success,cmd,line_post_cmd=get_token(line,' ')
	
	dbg_str=''
	
	cmd_esc='!'
		
	#if this was a command for the bot
	cmd_handled,cmd_dbg_str=handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,state_change,use_pg,db_login)
	if(cmd_handled):
		#then it's handled and we're done
		
		#debug if the command gave us a debug string
		dbg_str=cmd_dbg_str
	
	#support question/answer style markov chain-ing stuff
	elif(cmd.startswith(bot_nick)):
		output,dbg_str=markov.gen_from_str(state_change,use_pg,db_login,irc_str_map(line_post_cmd),random.randint(0,1)+1,retries_left=3,qa_sets=qa_sets)
		
		#if it didn't have that word as a starting state,
		#then just go random (fall back functionality)
		if(output==''):
			output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
		
		#properly close CTCP when it's generated
		if(output.startswith('\x01ACTION') and (not output.endswith('\x01'))):
			output+='\x01'
		
		#prevent generating commands directed towards other bots,
		#if configured to do that
		if(not gen_cmd):
			if(output.startswith('!')):
				output='\\'+output
		
#		dbg_str='[dbg] generated from line \"'+line_post_cmd+'\"'+"\n"+dbg_str
		dbg_str='[dbg] (\"'+line_post_cmd+'\") '+dbg_str
		
		py3queueln(sock,'PRIVMSG '+channel+' :'+output,1)
		
		#because people often talk to the bot in complete phrases,
		#go ahead and include these lines in the learning set
		lines_since_write,lines_since_sort_chk=learn_from(line,state_change,state_file,lines_since_write,lines_since_sort_chk)
		
		dbg_output(sock,dbg_str)
		
		return (lines_since_write,lines_since_sort_chk)
	
	#if it wasn't a command, then add this to the markov chain state and update the file on disk
	else:
		#if this was a pm then let the user know how to get help if they want it
		if(is_pm):
			py3queueln(sock,'PRIVMSG '+channel+' :learning... (use '+cmd_esc+'help to get help, or '+cmd_esc+'wut to generate text)',3)
		
		lines_since_write,lines_since_sort_chk=learn_from(line,state_change,state_file,lines_since_write,lines_since_sort_chk)
	
	#at ente's request; allow users in "debug" channels to read the bot's mind
	#this may or may not output, depending on the dbg_state global, but it is always called
	#because it stores a history for later output
	dbg_output(sock,dbg_str)
	
	return (lines_since_write,lines_since_sort_chk)
	

def handle_server_line(sock,line,state_change,state_file,lines_since_write,lines_since_sort_chk):
	global bot_nick
	
	#ignore blank lines
	if(line==''):
		return (lines_since_write,lines_since_sort_chk)
	
	#PONG back when we get a PING; this is needed for keepalive functionality
	if(line.startswith('PING')):
		success,ping,msg=get_token(line,' :')
		if(success):
			py3queueln(sock,'PONG :'+msg,0)
		return (lines_since_write,lines_since_sort_chk)
	#error, so exit
	elif(line.startswith('ERROR')):
		exit(1)
	
	success,server_name,line=get_token(line,' ')
	success,server_cmd,line=get_token(line,' ')
	
	#verbose debug
	if(server_cmd!='PRIVMSG'):
		log_line(server_name+' '+server_cmd+' '+line)
	
	#hello message received, so auto-join
	if(server_cmd=='001'):
		#mark us as being a bot (since we are)
		#on networks that recognize that
		py3queueln(sock,'MODE '+bot_nick+' +B',1)
		for channel in autojoin_channels+dbg_channels:
			py3queueln(sock,'JOIN :'+channel,1)
	#TODO: on a server JOIN message, add the specified channel information to the joined_channels dict
	elif(server_cmd=='JOIN'):
		pass
	#TODO: handle 353 names list, joins, and quits, to get a list of users for each channel we're in
	#which includes channel operator information
	#as channel operator information is necessary for oplist handling
	elif(server_cmd=='353'):
		pass
	#nick in use, so change nick
	elif(server_cmd=='433'):
		bot_nick+='_'
		py3queueln(sock,'NICK :'+bot_nick,1)
	#got a NICK change; update the bot_nick var if it's us
	#otherwise ignore
	#":confuseus!1@hostmask.com NICK :accirc_2"
	elif(server_cmd=='NICK'):
		name_mask=server_name.lstrip(':')
		bang_idx=name_mask.find('!')
		if(bang_idx>=0):
			old_nick=name_mask[0:bang_idx]
			new_nick=line.lstrip(':')
			if(old_nick==bot_nick):
				bot_nick=new_nick
	#got a PM, so reply
	elif(server_cmd=='PRIVMSG'):
		lines_since_write,lines_since_sort_chk=handle_privmsg(sock,server_name+' '+server_cmd+' '+line,state_change,state_file,lines_since_write,lines_since_sort_chk)
	#got an invite, so join
	elif(server_cmd=='INVITE'):
		succcesss,name,channel=get_token(line,' :')
		py3queueln(sock,'JOIN :'+channel,1)
	
	#TODO: add oplist-related handling here, specifically
	#for each channel this bot is in
	#	if there is at least one user authorized to have ops in this channel in the oplist_channels database table
	#		if this bot doesn't have ops in that channel
	#			and it's been at least 30 minutes since this bot asked for OPs last
	#			ping channel operators and ask them to grant OPs to the bot
	
	return (lines_since_write,lines_since_sort_chk)
	

def main(state_file,use_ssl=True):
	global bot_nick
	
	state_change=None
	if(not use_pg):
		print('Reading in state file...')
		state_change=markov.read_state_change_from_file(state_file)
	
	#if given an argument, it's the name to use
	if(len(sys.argv)>1):
		bot_nick=sys.argv[1]
	print('Bot Nick is '+bot_nick)
	
	print('Creating '+('encrypted' if use_ssl else 'UNENCRYPTED')+' connection to '+host+' on port '+str(port)+'...')
	
	#tcp client socket
	sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
	try:
		sock.connect((host,port))
		
		if(use_ssl):
			#use ssl
			#NOTE: this does NOT do cert checking and so could easily be mitm'd
			#but anything's better than nothing
			sock=ssl.wrap_socket(sock,do_handshake_on_connect=False)
	except:
		print('Err: Could not connect to '+host+' on port '+str(port))
		return 1
	
	#set the socket to be non-blocking
	#this will throw a socket.error when there is no data to read
	sock.setblocking(0)
	if(use_ssl):
		#we didn't actually do the handshake before we set non-blocking
		#so we need to do that now before we continue
		while True:
			try:
				sock.do_handshake()
				break
			except ssl.SSLWantReadError:
				select.select([sock], [], [])
			except ssl.SSLWantWriteError:
				select.select([], [sock], [])

	
	py3queueln(sock,'NICK :'+bot_nick)
	py3queueln(sock,'USER '+bot_nick+' 2 3 4')
	
	#initialize counters for events that only happen every n lines
	lines_since_write=100
	lines_since_sort_chk=100
	
	#carry from multi-line reads
	carry=''
	
	read_finished=True
	done=False
	while(not done):
		#if there is data from the user, then add that data to the outgoing queue
		#this allows the bot to act as a "puppet" or very primitive client
		stdin_data=select.select([sys.stdin],[],[],0.0)[0]
		while(len(stdin_data)>0):
			user_data=stdin_data[0].readline()
			user_data=user_data.rstrip("\n").rstrip("\r")
			print('Debug: user_data='+str(user_data))
			py3queueln(sock,user_data,1)
			
			stdin_data=stdin_data[1:]
		
		if(read_finished):
			#send a line from the outgoing queue
			#if the outgoing queue is empty this does nothing
			if(py3send_queue(sock)):
				#we want our queue priorities to actually matter
				#so after sending something, wait a second or 2
				#so that our receiving buffer can actually be ready to read any additional data
				#before we send more
				time.sleep(1.0)
		
		read_finished=False
		data=''
		try:
#			print('Dbg: Waiting for data...')
			data=py3recv(sock,BUFFER_SIZE)
		except ssl.SSLWantReadError:
			#wait 0.05 seconds before trying to read (or write) again
			#don't want to hog the CPU
			time.sleep(0.05)
			read_finished=True
			continue
		except socket.error as e:
			err=e.args[0]
			if(err==errno.EAGAIN or err==errno.EWOULDBLOCK):
				#wait 0.05 seconds before trying to read (or write) again
				#don't want to hog the CPU
				time.sleep(0.05)
				read_finished=True
			else:
				#if we got a real error (not just out of data) then exit
				print('Err: Socket Error: '+str(e))
				done=True
			continue
		
		#carry over from previous lines that weren't newline-terminated
		data=carry+data
		#and clear out the carry for next time
		carry=''
		
		line=''
		for i in range(0,len(data)):
			if(data[i]=="\r" or data[i]=="\n"):
				lines_since_write,lines_since_sort_chk=handle_server_line(sock,line,state_change,state_file,lines_since_write,lines_since_sort_chk)
				line=''
			else:
				line+=data[i]
		
		if(line!=''):
			carry=line
	
	print('Err: Connection Closed')
	
	#if we got here then we're totally finished
	#so close the socket
	sock.close()

#runtime
if(__name__=='__main__'):
	config_file=config.dflt_cfg
	if(len(sys.argv)>1):
		config_file=sys.argv[1]
	print('using JSON config file '+config_file)
	
	#read the configuration from the json configuration file
	json_cfg_tree=config.read_json_file(config_file)
	
	#set configuration from the config file
	#if configuration for anything is omitted a default value from the code is used
	
	#nick
	json_bot_nick=config.get_json_param(json_cfg_tree,'bot_nick')
	if(json_bot_nick!=None):
		bot_nick=json_bot_nick
	
	#channels to join on startup
	json_autojoin_channels=config.get_json_param(json_cfg_tree,'autojoin_channels')
	if(json_autojoin_channels!=None):
		autojoin_channels=json_autojoin_channels
	
	#debug channels to join and spam
	json_dbg_channels=config.get_json_param(json_cfg_tree,'dbg_channels')
	if(json_dbg_channels!=None):
		dbg_channels=json_dbg_channels
	
	#server connection information (host, port, encryption)
	json_host=config.get_json_param(json_cfg_tree,'host')
	if(json_host!=None):
		host=json_host
	json_port=config.get_json_param(json_cfg_tree,'port')
	if(json_port!=None):
		port=json_port
	json_use_ssl=config.get_json_param(json_cfg_tree,'use_ssl')
	if(json_use_ssl!=None):
		use_ssl=json_use_ssl
	
	#anti-spam settings (prevent generating commands to other bots, etc.)
	json_gen_cmd=config.get_json_param(json_cfg_tree,'gen_cmd')
	if(json_gen_cmd!=None):
		gen_cmd=json_gen_cmd
	
	#specially-handled user lists
	json_authed_users=config.get_json_param(json_cfg_tree,'authed_users')
	if(json_authed_users!=None):
		authed_users=json_authed_users
	json_ignored_users=config.get_json_param(json_cfg_tree,'ignored_users')
	if(json_ignored_users!=None):
		ignored_users=json_ignored_users
	
	#IRC-related configuration done
	
	#get question-answer sets from the configuration file
	#this feature is thanks to Mark (hey look I did it!)
	#these will be used to generate better responses to pre-formatted discussion
	json_answer_questions=config.get_json_param(json_cfg_tree,'answer_questions')
	if(json_answer_questions!=None):
		answer_questions=json_answer_questions
	
	#we allow disabling this function without requiring deleting all entries with the answer_questions bool
	if(answer_questions):
		json_qa_sets=config.get_json_param(json_cfg_tree,'qa_sets')
		if(json_qa_sets!=None):
			qa_sets=json_qa_sets
	else:
		qa_sets=[]
		
	
	#get markov (database) configuration
	
	use_pg=config.get_json_param(json_cfg_tree,'use_pg')
	if(use_pg==None):
		use_pg=False
	
	if(use_pg):
		#this is for the optional postgres backend
		config_tree=config.read_json_file(config_file)
		pg_user=config.get_json_param(config_tree,'pg_user')
		pg_passwd=config.get_json_param(config_tree,'pg_passwd')
		pg_dbname=config.get_json_param(config_tree,'pg_dbname')
		if(pg_user==None or pg_passwd==None or pg_dbname==None):
			print('Err: Need username, password, and db settings to use postgresql backend')
			use_pg=False
		else:
			db_login=markov.db_info(pg_user,pg_passwd,pg_dbname)
			print('using postgres database '+db_login.db_name+' for input and output of state changes')
	
	main(config.get_json_param(config.read_json_file(config_file),'state_file'),use_ssl=use_ssl)

