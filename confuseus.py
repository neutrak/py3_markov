#!/usr/bin/env python3

from socket import *
from py3net import *
import config
import http_cat
import markov
import random
import sys

#for the database backend which significantly reduces RAM use
use_pg=False
db_login=False
try:
	import postgresql
except ImportError:
	use_pg=False
	db_login=None

bot_nick='confuseus'
autojoin_channels=['#imgurians','#imgurians-tech']
#autojoin_channels=['#imgurians-tech'] #testing
host='us.ircnet.org'
port=6667

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

#unit conversion deg C to deg F
def c_to_f(c):
	return ((9.0/5.0)*c)+32

#unit conversion feet to meters
def ft_to_m(ft):
	return ft*0.3048

#unit conversion meters to feet
def m_to_ft(m):
	return m*3.281

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

def handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm,state_change,use_pg,db_login):
	handled=False
	
	#check if this was a bot command
	if((cmd==(cmd_esc+'wut')) or (cmd==cmd_esc)):
		output=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
		py3sendln(sock,'PRIVMSG '+channel+' :'+output)
		handled=True
	elif(cmd==(cmd_esc+'help')):
		if(is_pm):
			py3sendln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wut   -> generate text based on markov chains')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'help  -> displays this command list')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'part  -> parts current channel (you can invite to me get back)')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'f->c  -> converts temperature from deg F to deg C')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'c->f  -> converts temperature from deg C to deg F')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'m->ft -> converts length from meters to feet')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'ft->m -> converts length from feet to meters')
			py3sendln(sock,'PRIVMSG '+channel+' :'+cmd_esc+'wiki  -> [EXPERIMENTAL] grabs first paragraph from wikipedia')
		else:
			py3sendln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot; use '+cmd_esc+'wut to generate text; PM for more detailed help')
			
		handled=True
	elif(cmd==(cmd_esc+'part')):
		if(not is_pm):
			py3sendln(sock,'PART '+channel+' :Goodbye for now (you can invite me back any time)')
		else:
			py3sendln(sock,'PRIVMSG '+channel+' :part from where, asshole? this is a PM!')
		handled=True
	elif(cmd==(cmd_esc+'f->c')):
		try:
			f=float(line_post_cmd)
			c=f_to_c(f)
			py3sendln(sock,'PRIVMSG '+channel+' :'+str(f)+' degrees F is '+str(c)+' degrees C')
		except ValueError:
			py3sendln(sock,'PRIVMSG '+channel+' :Err: f->c requires a number, but I couldn\'t find one in your argument')
		handled=True
	elif(cmd==(cmd_esc+'c->f')):
		try:
			c=float(line_post_cmd)
			f=c_to_f(c)
			py3sendln(sock,'PRIVMSG '+channel+' :'+str(c)+' degrees C is '+str(f)+' degrees F')
		except ValueError:
			py3sendln(sock,'PRIVMSG '+channel+' :Err: c->f requires a number, but I couldn\'t find one in your argument')
		handled=True
	elif(cmd==(cmd_esc+'m->ft')):
		try:
			m=float(line_post_cmd)
			ft=m_to_ft(m)
			py3sendln(sock,'PRIVMSG '+channel+' :'+str(m)+' meters is '+str(ft)+' feet')
		except ValueError:
			py3sendln(sock,'PRIVMSG '+channel+' :Err: m->ft requires a number, but I couldn\'t find one in your argument')
		handled=True
	elif(cmd==(cmd_esc+'ft->m')):
		try:
			ft=float(line_post_cmd)
			m=ft_to_m(ft)
			py3sendln(sock,'PRIVMSG '+channel+' :'+str(ft)+' feet is '+str(m)+' meters')
		except ValueError:
			py3sendln(sock,'PRIVMSG '+channel+' :Err: ft->m requires a number, but I couldn\'t find one in your argument')
		handled=True
	elif(cmd==(cmd_esc+'wiki')):
		#TODO: handle more specific errors; this is super nasty but should keep the bot from crashing
		try:
			wiki_title=line_post_cmd.replace(' ','_')
			wiki_url='https://en.wikipedia.org/wiki/'+wiki_title
			response=http_cat.get_page(wiki_url)
			response_type=response[0].split("\n")[0].rstrip("\r")
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
			py3sendln(sock,'PRIVMSG '+channel+' :'+wiki_url)
		except:
			py3sendln(sock,'PRIVMSG '+channel+' :Err: wiki failed to get page text')
		handled=True
	elif(cmd.startswith(cmd_esc)):
#		py3sendln(sock,'PRIVMSG '+channel+' :Warn: Invalid command: \"'+cmd+'\"; see '+cmd_esc+'help for help')
		handled=True
	
	return handled


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
	
	cmd_esc='!'
	
	#support question/answer style markov chain-ing stuff
	if(cmd.startswith(bot_nick)):
		output=''
		
		#pick a random word the user said and start generating from there
		words=line_post_cmd.split(' ')
		if(len(words)>0):
			rand_word_idx=random.randint(0,len(words)-1)
			
			#sometimes back-generate and sometimes don't
			#just to mess with people :)
#			back_gen=bool(random.getrandbits(1))
			
			#back_gen broke cases where the user
			#intended confuseus to start from a given word
			#so it's disabled
			back_gen=False
			
			print('Chose a random word to start from ('+words[rand_word_idx]+'), back_gen is '+str(back_gen))
			
			#try to use a word from the user
			output=markov.generate(state_change,prefix=['',words[rand_word_idx]],acc=words[rand_word_idx],use_pg=use_pg,db_login=db_login,back_gen=back_gen)
			
		#if it didn't have that word as a starting state,
		#then just go random (fall back functionality)
		if(output=='' or output==words[rand_word_idx]):
			output=markov.generate(state_change,use_pg=use_pg,db_login=db_login,back_gen=False)
		
		py3sendln(sock,'PRIVMSG '+channel+' :'+output)
		
		#because people often talk to the bot in complete phrases,
		#go ahead and include these lines in the learning set
		lines_since_write,lines_since_sort_chk=learn_from(line,state_change,state_file,lines_since_write,lines_since_sort_chk)
		
		return (lines_since_write,lines_since_sort_chk)
		
	#if this was a command for the bot
	if(handle_bot_cmd(sock,cmd_esc,cmd,line_post_cmd,channel,is_pm,state_change,use_pg,db_login)):
		#then it's handled and we're done
		pass
	#if it wasn't a command, then add this to the markov chain state and update the file on disk
	else:
		#if this was a pm then let the user know how to get help if they want it
		if(is_pm):
			py3sendln(sock,'PRIVMSG '+channel+' :learning... (use '+cmd_esc+'help to get help, or '+cmd_esc+'wut to generate text)')
		
		lines_since_write,lines_since_sort_chk=learn_from(line,state_change,state_file,lines_since_write,lines_since_sort_chk)
	
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
		for channel in autojoin_channels:
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
	

def main(state_file):
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
	
	main(config.get_json_param(config.read_json_file(config_file),'state_file'))

