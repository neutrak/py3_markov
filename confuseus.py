#!/usr/bin/env python3

from socket import *
from py3net import *
import config
import http_cat
import markov
import random
import rpn
import sys
import time
import ssl
import json

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
dbg_channels=['+confuseus-dbg']
host='ssl.irc.atw-inter.net'
port=6697
use_ssl=True

#a list of all unit conversions we currently support
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
			py3sendln(sock,'PRIVMSG '+channel+' :'+round_nstr(from_val)+' '+self.from_disp+' is '+round_nstr(to_val)+' '+self.to_disp)
		except ValueError:
			py3sendln(sock,'PRIVMSG '+channel+' :Err: '+self.from_abbr+'->'+self.to_abbr+' requires a number, but I couldn\'t find one in your argument')

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
				py3sendln(sock,'PRIVMSG '+chan+' :'+line)
				time.sleep(random.uniform(0.1,1.5))

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


def handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm,state_change,use_pg,db_login):
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
		py3sendln(sock,'PRIVMSG '+channel+' :'+output)
		dbg_str='[dbg] generated from line \"'+line_post_cmd+'\"'+"\n"+dbg_str
		handled=True
	elif(cmd==(cmd_esc+'help')):
		if(is_pm):
			py3sendln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wut    -> generate text based on markov chains')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'help   -> displays this command list')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'part   -> parts current channel (you can invite to me get back)')
			for conversion in unit_conv_list:
				help_str='PRIVMSG '+channel+' :'+cmd_esc+conversion.from_abbr+'->'+conversion.to_abbr
				while(len(help_str)<len('PRIVMSG '+channel+' :'+cmd_esc+'XXXXXXX')):
					help_str+=' '
				help_str+='-> converts '+conversion.dimension+' from '+conversion.from_disp+' to '+conversion.to_disp
				py3sendln(sock,help_str)
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'calc   -> simple calculator; supports +,-,*,/,and ^; uses rpn internally')
#			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wiki   -> [EXPERIMENTAL] grabs first paragraph from wikipedia')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'source -> links the github url for this bot\'s source code')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'omdb   -> grabs movie information from the open movie database')
		else:
			py3sendln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot; use '+cmd_esc+'wut or address me by name to generate text; PM !help for more detailed help')
			
		handled=True
	elif(cmd==(cmd_esc+'part')):
		if(not is_pm):
			py3sendln(sock,'PART '+channel+' :Goodbye for now (you can invite me back any time)')
		else:
			py3sendln(sock,'PRIVMSG '+channel+' :part from where, asshole? this is a PM!')
		handled=True
	#conversions are their own function now
	elif(handle_conversion(sock,cmd_esc,cmd,line_post_cmd,channel)):
		handled=True
	elif(cmd==(cmd_esc+'calc')):
		result=rpn.rpn_eval(rpn.rpn_translate(line_post_cmd))
		if(len(result)==1):
			py3sendln(sock,'PRIVMSG '+channel+' :'+str(result[0]))
		else:
			py3sendln(sock,'PRIVMSG '+channel+' :Warn: An error occurred during evaluation; simplified RPN expression is '+str(result))
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
					is_pm,state_change,use_pg,db_login)
			
			if(response_type.find('200 OK')<0):
				py3sendln(sock,'PRIVMSG '+channel+' :Err: \"'+response_type+'\"')
			else:
				wiki_text=response[1]
				if(wiki_text==''):
					py3sendln(sock,'PRIVMSG '+channel+' :Err: wiki got null page text')
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
							py3sendln(sock,'PRIVMSG '+channel+' :'+wiki_text[0:prd_idx])
							wiki_text=wiki_text[prd_idx:]
						else:
							py3sendln(sock,'PRIVMSG '+channel+' :'+wiki_text[0:line_len])
							wiki_text=wiki_text[line_len:]
				py3sendln(sock,'PRIVMSG '+channel+' :'+wiki_url) #link the wiki page itself?
		except:
			py3sendln(sock,'PRIVMSG '+channel+' :Err: wiki failed to get page text')
		handled=True
	elif(cmd==(cmd_esc+'source')):
		py3sendln(sock,'PRIVMSG '+channel+' :bot source code: '+SOURCE_CODE_URL)
		handled=True
	elif(cmd==(cmd_esc+'omdb')):
		if(line_post_cmd!=''):
			title_words=line_post_cmd.rstrip(' ').split(' ')
			for i in range(0,len(title_words)):
				if(title_words[i][0]==title_words[i][0].lower()):
					title_words[i]=title_words[i][0].upper()+title_words[i][1:]
			url='http://www.omdbapi.com/?t='+('+'.join(title_words))+'&y=&plot=short&r=json'
			try:
				response=http_cat.get_page(url)
			except:
				py3sendln(sock,'PRIVMSG '+channel+' :Err: Could not retrieve data (weird characters in title?)')
				return (True,dbg_str)
			
			response_type=response[0].split("\n")[0].rstrip("\r")
			if(response_type.find('200 OK')<0):
				py3sendln(sock,'PRIVMSG '+channel+' :Err: \"'+response_type+'\"')
			else:
				try:
					json_tree=json.loads(response[1])
				except ValueError:
					py3sendln(sock,'PRIVMSG '+channel+' :Err: Could not parse json response from omdb')
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
				
				py3sendln(sock,'PRIVMSG '+channel+' :'+title+' / '+rating+' / '+year+' / '+genre+' / '+plot)
		else:
			py3sendln(sock,'PRIVMSG '+channel+' :Err: omdb requires a movie title as a parameter')
		handled=True

	elif(cmd.startswith(cmd_esc)):
#		py3sendln(sock,'PRIVMSG '+channel+' :Warn: Invalid command: \"'+cmd+'\"; see '+cmd_esc+'help for help')
		handled=True
	#this was added at the request of NuclearWaffle, in an attempt, and I'm quoting here
	#to "fuck with Proview"
#	elif((len(cmd)>1) and odd_quest(cmd)):
#		output,dbg_str=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
#		py3sendln(sock,'PRIVMSG '+channel+' :'+output)
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
		
		py3sendln(sock,'PRIVMSG '+channel+' :'+output)
		
		#because people often talk to the bot in complete phrases,
		#go ahead and include these lines in the learning set
		lines_since_write,lines_since_sort_chk=learn_from(line,state_change,state_file,lines_since_write,lines_since_sort_chk)
		
		dbg_output(sock,dbg_str)
		
		return (lines_since_write,lines_since_sort_chk)
		
	#if this was a command for the bot
	cmd_handled,cmd_dbg_str=handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm,state_change,use_pg,db_login)
	if(cmd_handled):
		#then it's handled and we're done
		
		#debug if the command gave us a debug string
		dbg_str=cmd_dbg_str
	#if it wasn't a command, then add this to the markov chain state and update the file on disk
	else:
		#if this was a pm then let the user know how to get help if they want it
		if(is_pm):
			py3sendln(sock,'PRIVMSG '+channel+' :learning... (use '+cmd_esc+'help to get help, or '+cmd_esc+'wut to generate text)')
		
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
			py3sendln(sock,'PONG :'+msg)
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
		for channel in autojoin_channels+dbg_channels:
			py3sendln(sock,'JOIN :'+channel)
	#nick in use, so change nick
	elif(server_cmd=='433'):
		bot_nick+='_'
		py3sendln(sock,'NICK :'+bot_nick)
	#got a PM, so reply
	elif(server_cmd=='PRIVMSG'):
		lines_since_write,lines_since_sort_chk=handle_privmsg(sock,server_name+' '+server_cmd+' '+line,state_change,state_file,lines_since_write,lines_since_sort_chk)
	#got an invite, so join
	elif(server_cmd=='INVITE'):
		succcesss,name,channel=get_token(line,' :')
		py3sendln(sock,'JOIN :'+channel)
	
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
	sock=socket(AF_INET,SOCK_STREAM)
	try:
		sock.connect((host,port))
		
		if(use_ssl):
			#do an ssl handshake and use ssl
			#NOTE: this does NOT do cert checking and so could easily be mitm'd
			#but anything's better than nothing
			sock=ssl.wrap_socket(sock)
	except:
		print('Err: Could not connect to '+host+' on port '+str(port))
		return 1
	
	
	py3sendln(sock,'NICK :'+bot_nick)
	py3sendln(sock,'USER '+bot_nick+' 2 3 4')
	
	#initialize counters for events that only happen every n lines
	lines_since_write=100
	lines_since_sort_chk=100
	
	#carry from multi-line reads
	carry=''
	
	done=False
	while(not done):
		data=py3recv(sock,BUFFER_SIZE)
		
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

