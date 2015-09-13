#!/usr/bin/python3

import sys
import socket
from py3net import *

def separate_http_header(http_response):
	http_header=""
	
	header_finished=False
	while(not header_finished):
		#check for windows newlines
		newline="\r\n"
		newline_idx=http_response.find(newline)
		#no windows newlines, check for proper *nix newlines
		if(newline_idx<0):
			newline="\n"
			newline_idx=http_response.find(newline)
		
		#there are no newlines but we're not finished with the header, return empty (error)
		if(newline_idx<0):
			return [http_header,""]
		
		#this is a header field, remember that
		http_header+=http_response[0:newline_idx+len(newline)]
		
		#two newlines right after each other define end-of-header
		if(newline_idx==0):
			header_finished=True
		
		http_response=http_response[newline_idx+len(newline):len(http_response)]
	
	return [http_header,http_response]

def get_page(url,port=80):
	#strip off the protocol (we assume http or https)
	protocol_idx=url.find('://')
	protocol_str='http'
	if(protocol_idx>=0):
		protocol_str=url[0:protocol_idx].lower()
		url=url[protocol_idx+len('://'):len(url)]
	print('Protocol: '+protocol_str)
	
	path_idx=url.find('/')
	if(path_idx<0):
		path_idx=len(url)
	
	domain=url[0:path_idx]
	port_str=''
	colon_idx=domain.find(':')
	if(colon_idx>=0):
		port_str=domain[colon_idx+1:]
		domain=domain[:colon_idx]
	print('Domain: '+domain)
#	print('Port String: '+port_str)
	
	path=url[path_idx:]
	if(path==''):
		path='/'
	print('Path: '+path)
	print("\n\n")
	
	http_rqst=''
	http_rqst+='GET '+path+' HTTP/1.0'+"\n"
	http_rqst+='Host:'+domain+"\n"
	http_rqst+='User-Agent:confuseus (an irc bot, like internet explorer)'+"\n"
	http_rqst+="\n"
	
	print(http_rqst)
	
	s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.settimeout(3.0)
	if(protocol_str=='https'):
		import ssl
		s=ssl.wrap_socket(s,cert_reqs=ssl.CERT_NONE) #NOTE: cert checking is not done here
#		s=ssl.wrap_socket(s,cert_reqs=ssl.CERT_NONE,do_handshake_on_connect=True,ssl_version=ssl.PROTOCOL_TLSv1_2) #NOTE: cert checking is not done here
	s.connect((domain,port))
	py3send(s,http_rqst)
	
	response=''
	while(1):
		recv_data=py3recv(s,BUFFER_SIZE)
		if(not recv_data):
			break
		response+=recv_data
	s.close()
	
	return separate_http_header(response)

def html_strip_tags(text):
	nest_lvl=0
	raw_text=''
	for idx in range(0,len(text)):
		if(text[idx]=='<'):
			nest_lvl+=1
		elif(text[idx]=='>'):
			nest_lvl-=1
		elif(nest_lvl==0):
			raw_text+=text[idx]
	return raw_text

def html_parse_first(text,start,end):
	start_idx=text.find(start)
	if(start_idx<0):
		return html_strip_tags(text)
	start_idx+=len(start)
	end_idx=text[start_idx:].find(end)+start_idx
	return html_strip_tags(text[start_idx:end_idx])

def main():
	if(len(sys.argv)<2):
		print("Usage: "+sys.argv[0]+" <url to fetch>")
		return 1
	response=(get_page(sys.argv[1]))
	for i in range(0,len(response)):
		print(response[i])
	
	print("\n\n\n\n"+'first paragraph:')
	print(html_parse_first(response[1],'<p>','</p>'))

if(__name__=='__main__'):
	main()

