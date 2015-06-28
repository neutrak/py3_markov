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

#for the database backend which significantly reduces RAM use
use_pg=False
db_login=False
try:
	import postgresql
except ImportError:
	use_pg=False
	db_login=None

SOURCE_CODE_URL='https://github.com/neutrak/py3_markov'

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

#users allowed to !shup the bot
#(aka clear outgoing queue)
#TODO: if this list is ever used for anything more important, be sure to authenticate in some way, or at least check for channel ops
authed_users=[]

#users to ignore (bots)
#this is a blacklist, like /ignore in many clients
ignored_users=[]

#END JSON-configurable globals ==========================================================

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
	for chan in dbg_channels:
		for line in dbg_str.split("\n"):
			if(line!=''):
				py3queueln(sock,'PRIVMSG '+chan+' :'+line,4)
#				time.sleep(random.uniform(0.1,1.5))

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

def handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,state_change,use_pg,db_login):
	global gen_cmd
	global unit_conv_list
	handled=False
	
	dbg_str=''
	
	#check if this was a bot command
	if((cmd==(cmd_esc+'wut')) or (cmd==cmd_esc)):
		output=''
		if(line_post_cmd!=''):
			output,dbg_str=markov.gen_from_str(state_change,use_pg,db_login,irc_str_map(line_post_cmd),random.randint(0,1)+1,retries_left=3)
		if(output==''):
			output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
		
		#prevent generating commands directed towards other bots,
		#if configured to do that
		if(not gen_cmd):
			if(output.startswith('!')):
				output='\\'+output
		
		py3queueln(sock,'PRIVMSG '+channel+' :'+output,1)
		dbg_str='[dbg] generated from line \"'+line_post_cmd+'\"'+"\n"+dbg_str
		handled=True
	elif(cmd==(cmd_esc+'help')):
		if(is_pm):
			py3queueln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wut                       -> generate text based on markov chains',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'help                      -> displays this command list',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'shup [min nice lvl]       -> clears low-priority messages from sending queue (authorized users can clear higher priority messages)',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'part                      -> parts current channel (you can invite to me get back)',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'calc <expression>         -> simple calculator; supports +,-,*,/,and ^; uses rpn internally',3)
#			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wiki <topic>              -> [EXPERIMENTAL] grabs first paragraph from wikipedia',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'source                    -> links the github url for this bot\'s source code',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'omdb <movie name>         -> grabs movie information from the open movie database',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'splchk <word> [edit dist] -> checks given word against a dictionary and suggests fixes',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'dieroll [sides]           -> generates random number in range [1,sides]',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'time [utc offset tz]      -> tells current UTC time, or if a timezone is given, current time in that timezone',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'timecalc <%R> <tz1> <tz2> -> tells what the given time (%R == hours:minutes on a 24-hour clock) at the first utc-offset timezone will be at the second utc-offset timezone',3)
			for conversion in unit_conv_list:
				help_str='PRIVMSG '+channel+' :'+cmd_esc+conversion.from_abbr+'->'+conversion.to_abbr+' <value>'
				while(len(help_str)<len('PRIVMSG '+channel+' :'+cmd_esc+'XXXXXXXXXXXXXXXXXXXXXXXXXX')):
					help_str+=' '
				help_str+='-> converts '+conversion.dimension+' from '+conversion.from_disp+' to '+conversion.to_disp
				py3queueln(sock,help_str,3)

		else:
			py3queueln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot; use '+cmd_esc+'wut or address me by name to generate text; PM !help for more detailed help',3)
			
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
		err_msgs,result=rpn.rpn_eval(rpn.rpn_translate(line_post_cmd))
		if(len(result)==1):
			py3queueln(sock,'PRIVMSG '+channel+' :'+str(result[0]),1)
		else:
			py3queueln(sock,'PRIVMSG '+channel+' :Warn: An error occurred during evaluation; simplified RPN expression is '+str(result),1)
			for err_idx in range(0,len(err_msgs)):
				py3queueln(sock,'PRIVMSG '+channel+' :Err #'+str(err_idx)+': '+str(err_msgs[err_idx]),3)
		handled=True
	elif(cmd==(cmd_esc+'wiki')):
		#disabled because we have another bot to do this now
		return (True,dbg_str)
		
		#TODO: handle more specific errors; this is super nasty but should keep the bot from crashing
		try:
			wiki_title=line_post_cmd.replace(' ','_')
			wiki_url='https://en.wikipedia.org/wiki/'+wiki_title
			response=http_cat.get_page(wiki_url)
			
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
					#get the first paragraph and throw out nested html tags
					wiki_text=http_cat.html_parse_first(wiki_text,'<p>','</p>')
					max_p_len=768
					wiki_text=wiki_text[0:max_p_len]
					line_len=300
					while(wiki_text!=''):
						line_delimiter='. '
						prd_idx=wiki_text.find(line_delimiter)
						if(prd_idx>=0):
							prd_idx+=len(line_delimiter)
							py3queueln(sock,'PRIVMSG '+channel+' :'+wiki_text[0:prd_idx],1)
							wiki_text=wiki_text[prd_idx:]
						else:
							py3queueln(sock,'PRIVMSG '+channel+' :'+wiki_text[0:line_len],1)
							wiki_text=wiki_text[line_len:]
				py3queueln(sock,'PRIVMSG '+channel+' :'+wiki_url,1) #link the wiki page itself?
		except:
			py3queueln(sock,'PRIVMSG '+channel+' :Err: wiki failed to get page text',1)
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
	#this was added at the request of NuclearWaffle, in an attempt, and I'm quoting here
	#to "fuck with Proview"
#	elif((len(cmd)>1) and odd_quest(cmd)):
#		output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
#		
#		#prevent generating commands directed towards other bots,
#		#if configured to do that
#		if(not gen_cmd):
#			if(output.startswith('!')):
#				output='\\'+output
#		
#		py3queueln(sock,'PRIVMSG '+channel+' :'+output,1)
#		handled=True
	
	return (handled,dbg_str)


def handle_privmsg(sock,line,state_change,state_file,lines_since_write,lines_since_sort_chk):
	global gen_cmd
	
	#get some information (user, nick, host, etc.)
	success,info,line=get_token(line,' ')
	info=info.lstrip(':')
	success,nick,info=get_token(info,'!')
	success,realname,info=get_token(info,'@')
	success,hostmask,info=get_token(info,' ')
	success,privmsg_cmd,line=get_token(line,' ')
	success,channel,line=get_token(line,' ')
	
	if(line.startswith(':')):
		line=line[1:]
	
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
	
	#at ente's request; allow users in "debug" channels to read the bot's mind
#	net_dbg=False
	net_dbg=True
	
	cmd_esc='!'
	
	#support question/answer style markov chain-ing stuff
	if(cmd.startswith(bot_nick)):
		output,dbg_str=markov.gen_from_str(state_change,use_pg,db_login,irc_str_map(line_post_cmd),random.randint(0,1)+1,retries_left=3)
		
		#if it didn't have that word as a starting state,
		#then just go random (fall back functionality)
		if(output==''):
			output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
		
		#prevent generating commands directed towards other bots,
		#if configured to do that
		if(not gen_cmd):
			if(output.startswith('!')):
				output='\\'+output
		
		dbg_str='[dbg] generated from line \"'+line_post_cmd+'\"'+"\n"+dbg_str
		
		py3queueln(sock,'PRIVMSG '+channel+' :'+output,1)
		
		#because people often talk to the bot in complete phrases,
		#go ahead and include these lines in the learning set
		lines_since_write,lines_since_sort_chk=learn_from(line,state_change,state_file,lines_since_write,lines_since_sort_chk)
		
		dbg_output(sock,dbg_str)
		
		return (lines_since_write,lines_since_sort_chk)
		
	#if this was a command for the bot
	cmd_handled,cmd_dbg_str=handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,state_change,use_pg,db_login)
	if(cmd_handled):
		#then it's handled and we're done
		
		#debug if the command gave us a debug string
		dbg_str=cmd_dbg_str
	#if it wasn't a command, then add this to the markov chain state and update the file on disk
	else:
		#if this was a pm then let the user know how to get help if they want it
		if(is_pm):
			py3queueln(sock,'PRIVMSG '+channel+' :learning... (use '+cmd_esc+'help to get help, or '+cmd_esc+'wut to generate text)',3)
		
		lines_since_write,lines_since_sort_chk=learn_from(line,state_change,state_file,lines_since_write,lines_since_sort_chk)
	
	#if we're debugging over the network, then output to the debug channels
	if(net_dbg):
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
	#nick in use, so change nick
	elif(server_cmd=='433'):
		bot_nick+='_'
		py3queueln(sock,'NICK :'+bot_nick,1)
	#got a PM, so reply
	elif(server_cmd=='PRIVMSG'):
		lines_since_write,lines_since_sort_chk=handle_privmsg(sock,server_name+' '+server_cmd+' '+line,state_change,state_file,lines_since_write,lines_since_sort_chk)
	#got an invite, so join
	elif(server_cmd=='INVITE'):
		succcesss,name,channel=get_token(line,' :')
		py3queueln(sock,'JOIN :'+channel,1)
	
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
	base_sock=None
	try:
		sock.connect((host,port))
		
		if(use_ssl):
			#store the non-ssl underlying socket
			#because we need to set non-blocking on THAT
			base_sock=sock
			
			#do an ssl handshake and use ssl
			#NOTE: this does NOT do cert checking and so could easily be mitm'd
			#but anything's better than nothing
			sock=ssl.wrap_socket(sock)
	except:
		print('Err: Could not connect to '+host+' on port '+str(port))
		return 1
	
	#set the socket to be non-blocking
	#this will throw a socket.error when there is no data to read
	if(use_ssl):
		base_sock.setblocking(0)
	sock.setblocking(0)
	
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

