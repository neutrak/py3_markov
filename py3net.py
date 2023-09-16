#a simple wrapper for networking functions in python3

import time

BUFFER_SIZE=1024

#a sending queue that includes priority
#priorities are nice values (i.e. highest number is lowest priority)
#this can be combined with sorting to give a proper
send_queue=[]

#log a line to a file, and also output it for debugging
def log_line(line,log_file='log.txt'):
	#timestamp the line
	line=str(int(time.time()))+' '+line
	
	#debug
	print(line)
	
	if(log_file!=None):
		fp=open(log_file,'a')
		fp.write(line+"\n")
		fp.close()

#send a string to a socket in python3
#s is the socket
def py3send(s,message):
	try:
		s.send(message.encode('utf-8','replace'))
	except UnicodeEncodeError:
		print('Err: Unicode conversion error, ignoring message '+str(message))

def py3sendln(s,message):
	log_line('>> '+message)
	
	py3send(s,message+"\n")

#queue up a line to send but don't send it just yet
def py3queueln(s,message,priority=1):
	global send_queue
	send_queue.append((message,priority))

#send one line from the front of the queue
#returns True if data was sent, False if not
def py3send_queue(s,debug=False):
	global send_queue
	
	#sort messages by priority before sending
	send_queue.sort(key=lambda m: m[1])
	
	if(len(send_queue)>0):
		if(debug):
			print('Dbg: There are '+str(len(send_queue))+' messages in the queue; the queue is '+str(send_queue))
		message=send_queue[0][0]
		py3sendln(s,message)
		send_queue=send_queue[1:]
		return True
	return False

#flush the queue, sending all lines in the correct priority-based order
def py3flushq(s):
	global send_queue
	
	#clear out the sending queue
	#and do it in the correct order based on priority
	while(len(send_queue)>0):
		py3sendqueue(s)

#clear the queue WITHOUT sending
#this can LOSE output!!!
def py3clearq(min_nice_val):
	global send_queue
	
	#make a new send queue which discards those messages
	#whose nice value is >= the given minimum
	#(aka given priority or lower)
	new_send_queue=[]
	for entry in send_queue:
		if(entry[1]<min_nice_val):
			new_send_queue.append(entry)
	
	send_queue=new_send_queue

#receive a string in python3
def py3recv(s,byte_count):
	try:
		data=s.recv(byte_count)
		if(not data):
			return data
		return data.decode('utf-8')
	except UnicodeDecodeError:
		print('Err: Unicode conversion error, ignoring this line')
	return ''


