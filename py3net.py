#a simple wrapper for networking functions in python3

import time

BUFFER_SIZE=1024

#log a line to a file, and also output it for debugging
def log_line(line,log_file='log.txt'):
	#timestamp the line
	line=str(int(time.time()))+' '+line
	
	#debug
	print(line)
	
	fp=open(log_file,'a')
	fp.write(line+"\n")
	fp.close()

#send a string to a socket in python3
#s is the socket
def py3send(s,message):
	try:
		s.send(message.encode('latin-1'))
	except UnicodeEncodeError:
		print('Err: Unicode to latin-1 conversion error, ignoring message '+str(message))

def py3sendln(s,message):
	log_line('>> '+message)
	
	py3send(s,message+"\n")

#receive a string in python3
def py3recv(s,byte_count):
	try:
		data=s.recv(byte_count)
		if(not data):
			return data
		return data.decode('utf-8')
	except UnicodeDecodeError:
		print('Err: latin-1 to Unicode conversion error, ignoring this line')
	return ''


