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

#for the database backend which significantly reduces RAM use
use_pg=False
db_login=False
try:
	import postgresql
except ImportError:
	use_pg=False
	db_login=None

SOURCE_CODE_URL='https://github.com/neutrak/py3_markov'

bot_nick='confuseus'

autojoin_channels=['#imgurians','#imgurians-tech']
#autojoin_channels=['#imgurians-tech'] #testing
#autojoin_channels=[]

dbg_channels=['+confuseus-dbg']
#dbg_channels=[]

host='ssl.irc.atw-inter.net'
port=6697
use_ssl=True

#host='us.ircnet.org'
#port=6667
#use_ssl=False

#users allowed to !shup the bot
#(aka clear outgoing queue)
#TODO: if this list is ever used for anything more important, be sure to authenticate in some way, or at least check for channel ops
authed_users=['neutrak','NuclearWaffle','Proview','ente','GargajCNS','tard','hobbitlover','thetardis','Tanswedes']

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
	return mi*1.609334

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
			return (True,dbg_str)
		
		response_type=response[0].split("\n")[0].rstrip("\r")
		if(response_type.find('200 OK')<0):
			py3queueln(sock,'PRIVMSG '+channel+' :Err: \"'+response_type+'\"',1)
		else:
			try:
				json_tree=json.loads(response[1])
			except ValueError:
				py3queueln(sock,'PRIVMSG '+channel+' :Err: Could not parse json response from omdb',1)
				return (True,dbg_str)
			
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


def handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,nick,is_pm,state_change,use_pg,db_login):
	global unit_conv_list
	handled=False
	
	dbg_str=''
	
	#check if this was a bot command
	if((cmd==(cmd_esc+'wut')) or (cmd==cmd_esc)):
		output=''
		if(line_post_cmd!=''):
			output,dbg_str=markov.gen_from_str(state_change,use_pg,db_login,line_post_cmd,random.randint(0,1)+1,retries_left=3)
		if(output==''):
			output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
		py3queueln(sock,'PRIVMSG '+channel+' :'+output,1)
		dbg_str='[dbg] generated from line \"'+line_post_cmd+'\"'+"\n"+dbg_str
		handled=True
	elif(cmd==(cmd_esc+'help')):
		if(is_pm):
			py3queueln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wut                       -> generate text based on markov chains',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'help                      -> displays this command list',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'shup                      -> clears sending queue (authorized users only)',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'part                      -> parts current channel (you can invite to me get back)',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'calc <expression>         -> simple calculator; supports +,-,*,/,and ^; uses rpn internally',3)
#			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wiki <topic>              -> [EXPERIMENTAL] grabs first paragraph from wikipedia',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'source                    -> links the github url for this bot\'s source code',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'omdb <movie name>         -> grabs movie information from the open movie database',3)
			py3queueln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'splchk <word> [edit dist] -> checks given word against a dictionary and suggests fixes',3)
			for conversion in unit_conv_list:
				help_str='PRIVMSG '+channel+' :'+cmd_esc+conversion.from_abbr+'->'+conversion.to_abbr+' <value>'
				while(len(help_str)<len('PRIVMSG '+channel+' :'+cmd_esc+'XXXXXXXXXXXXXXXXXXXXXXXXXX')):
					help_str+=' '
				help_str+='-> converts '+conversion.dimension+' from '+conversion.from_disp+' to '+conversion.to_disp
				py3queueln(sock,help_str,3)

		else:
			py3queueln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot; use '+cmd_esc+'wut or address me by name to generate text; PM !help for more detailed help',3)
			
		handled=True
	elif((cmd==(cmd_esc+'shup')) or (cmd==(cmd_esc+'shoo'))):
		if(nick in authed_users):
			py3clearq()
			py3queueln(sock,'PRIVMSG '+channel+' :Outgoing message queue cleared! (someone might be pissed at you if they\'re waiting on output)',1)
		else:
			py3queueln(sock,'PRIVMSG '+channel+' :'+nick+': you\'re not authorized to use '+cmd_esc+'shup; queue NOT cleared',1)
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
	elif(cmd==(cmd_esc+'omdb')):
		handle_omdb(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	elif((cmd==(cmd_esc+'splchk')) or (cmd==(cmd_esc+'spellcheck')) or (cmd==(cmd_esc+'sp')) or (cmd==(cmd_esc+'spell'))):
		handle_spellcheck(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm)
		handled=True
	elif(cmd.startswith(cmd_esc)):
		if(is_pm):
			py3queueln(sock,'PRIVMSG '+channel+' :Warn: Invalid command: \"'+cmd+'\"; see '+cmd_esc+'help for help',1)
		
		#this prevents the bot from learning from unrecognized ! commands
		#(which are usually meant for another bot)
#		handled=True
	#this was added at the request of NuclearWaffle, in an attempt, and I'm quoting here
	#to "fuck with Proview"
#	elif((len(cmd)>1) and odd_quest(cmd)):
#		output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
#		py3queueln(sock,'PRIVMSG '+channel+' :'+output,1)
#		handled=True
	
	return (handled,dbg_str)


def handle_privmsg(sock,line,state_change,state_file,lines_since_write,lines_since_sort_chk):
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
		output,dbg_str=markov.gen_from_str(state_change,use_pg,db_login,line_post_cmd,random.randint(0,1)+1,retries_left=3)
		
		#if it didn't have that word as a starting state,
		#then just go random (fall back functionality)
		if(output==''):
			output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
		
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
	
	print('Creating connection to '+host+' on port '+str(port)+'...')
	
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
	
	use_pg=config.get_json_param(config.read_json_file(config_file),'use_pg')
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

