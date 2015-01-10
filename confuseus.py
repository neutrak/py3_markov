#!/usr/bin/env python3

from socket import *
import markov

bot_nick='confuseus'
autojoin_channels=['#imgurians']
host='us.ircnet.org'
#host='daemonic.foonetic.net'
port=6667

buffer_size=1024

#send a string to a socket in python3
#s is the socket
def py3send(s,message):
	s.send(message.encode('latin-1'))

def py3sendln(s,message):
	#debug
	print('>> '+message)
	
	py3send(s,message+"\n")

#receive a string in python3
def py3recv(s,byte_count):
	data=s.recv(byte_count)
	return data.decode('utf-8')

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

def handle_privmsg(sock,line,state_change,state_file):
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
	print('['+channel+'] <'+nick+'> '+line)
	
	#if they PM'd us, then PM 'em right back
	#that'll show 'em
	if(channel==bot_nick):
		channel=nick
	
	success,cmd,tmp=get_token(line,' ')
	
	#check if this was a bot command
	if(cmd=='+wut'):
		output=markov.generate(state_change)
		py3sendln(sock,'PRIVMSG '+channel+' :'+output)
	elif(cmd=='+help'):
		py3sendln(sock,'PRIVMSG '+channel+' :This is a simple markov chain bot, use +wut to generate text.  That is the only supported feature currently (I might add unit conversions or something later).  ')
	#if it wasn't a command, then add this to the markov chain state and update the file on disk
	else:
		state_change=markov.chain_from(line,state_change,prefix=['',''])
		markov.save_state_change_to_file(state_change,state_file)
		pass
	

def handle_server_line(sock,line,state_change,state_file):
	#ignore blank lines
	if(line==''):
		return
	
	#verbose debug
	print(line)
	
	if(line.startswith('PING')):
		success,ping,msg=get_token(line,' :')
		if(success):
			py3sendln(sock,'PONG :'+msg)
		return
	#error, so exit
	elif(line.startswith('ERROR')):
		exit(1)
	
	success,server_name,line=get_token(line,' ')
	success,server_cmd,line=get_token(line,' ')
	
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
		handle_privmsg(sock,server_name+' '+server_cmd+' '+line,state_change,state_file)
	#got an invite, so join
	elif(server_cmd=='INVITE'):
		pass
	

def main(state_file='state_file.txt'):
	print('Reading in state file...')
	state_change=markov.read_state_change_from_file(state_file)
	
	print('Creating connection to '+host+' on port '+str(port)+'...')
	
	#tcp client socket
	sock=socket(AF_INET,SOCK_STREAM)
	try:
		sock.connect((host,port))
	except:
		print('Err: Could not connect to '+host+' on port '+str(port))
		return 1
	
	
	py3sendln(sock,'NICK :'+bot_nick)
	py3sendln(sock,'USER 1 2 3 4')
	
	#carry from multi-line reads
	carry=''
	
	done=False
	while(not done):
		data=py3recv(sock,buffer_size)
		
		#carry over from previous lines that weren't newline-terminated
		data=carry+data
		#and clear out the carry for next time
		carry=''
		
		line=''
		for i in range(0,len(data)):
			if(data[i]=="\r" or data[i]=="\n"):
				handle_server_line(sock,line,state_change,state_file)
				line=''
			else:
				line+=data[i]
		
		if(line!=''):
			carry=line

#runtime
if(__name__=='__main__'):
	main()

