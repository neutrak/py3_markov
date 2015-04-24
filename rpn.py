#!/usr/bin/python3

#this takes any math expression and produces an unambiguous RPN representation
#it is an implementation of (among other things) the shunting-yard algorithm
#it supports the following operators
#   ^ -> exponent (a^b)
#   * -> multiplcation (a*b)
#   / -> division (a/b)
#   % -> modulo (a%b)
#   + -> addition (a+b)
#   - -> subtraction (a-b); this is NOT a unary operator, it requires two operands; for negatives use (0-a)
#   && -> boolean and, returns 1 for true, 0 for false (a && b)
#   || -> boolean or, returns 1 for true, 0 for false (a || b)
#   ~ -> not operator, returns 1 for true, 0 for false (~a)
#   > -> greater than operator (a>b)
#   < -> less than operator (a<b)
#   = -> equal to operator (a=b)

#TODO: fix the not operator, '~'; it is complex because it is a unary prefix operator and all other operators are binary infix
#an example of how this is broken can be seen by running on the input "6 * ~5 + 3"; this should yeild 3, but instead fails to complete because there aren't enough arguments for *
#despite known errors I have left the not operator in, because correct behavior can be introduced with parentheses and it's sometimes a necessary operator

import sys

#does operator a have precedence over operator b?
def op_precedence(op_a,op_b):
	has_precedence=False
	
	#unary operators get precedence above all else
	#the not operator is a unary operator
	if(op_a=='~'):
		has_precedence=True
	#of binary operators, exponents are highest precedence
	elif(op_a=='^'):
		#they are also right-associative
		if(op_b!='^'):
			has_precedence=True
	#followed by multiplication, division, and modulo (since modulo is division)
	elif(op_a=='*' or op_a=='/' or op_a=='%'):
		#these get precedence over everything but ^ (including themselves, due to left associativity)
		if(op_b!='^'):
			has_precedence=True
	#and finally addition and subtraction
	elif(op_a=='+' or op_a=='-'):
		#these get precedence over each other (and themselves) due to left associativity
		if(op_b=='+' or op_b=='-' or op_b=='&&' or op_b=='||' or op_b=='~'):
			has_precedence=True
	#comparisons aren't proper operators and get lowest precedence aside from booleans
	elif(op_a=='>' or op_a=='<' or op_a=='='):
		if(op_b=='>' or op_b=='<' or op_b=='=' or op_b=='&&' or op_b=='||'):
			has_precedence=True
	#booleans are not even proper operators and get the lowest precedence
	elif(op_a=='&&' or op_a=='||'):
		#these get precedence over each other (and themselves) due to left associativity
		if(op_b=='&&' or op_b=='||'):
			has_precedence=True
	
	return has_precedence

#sort an operator stack by precedence
#this uses a variation on mergesort
def precedence_sort(op_stack):
	#a stack with 0 or 1 items is already sorted by definition
	if(len(op_stack)<2):
		return op_stack
	
	#choose the first item as a pivot
	pivot=op_stack[0]
	
	#find all operators with lower precedence
	low_prec=[]
	#and all with higher precedence
	high_prec=[]
	for i in range(1,len(op_stack)):
		if(op_precedence(pivot,op_stack[i])):
			low_prec.append(op_stack[i])
		else:
			high_prec.append(op_stack[i])
	
	#sort each individual sub-list
	high_prec=precedence_sort(high_prec)
	low_prec=precedence_sort(low_prec)
	
	#now put it all back together
	new_op_stack=[]
	for i in range(0,len(low_prec)):
		new_op_stack.append(low_prec[i])
	
	new_op_stack.append(pivot)
	
	for i in range(0,len(high_prec)):
		new_op_stack.append(high_prec[i])
	
	return new_op_stack
	
#adds an operator to the output based on precedence rules
def add_op(out_acc,op_stack,new_op):
#	print('add_op debug 0, before sorting op_stack='+str(op_stack))
	#sort op_stack by priority where appropriate
#	op_stack=precedence_sort(op_stack)
#	print('add_op debug 1, after sorting op_stack='+str(op_stack))
	
	#if there are no operators then don't bother with precedence rules for them
	if(len(op_stack)>0):
		#get the first operator
		active_op=op_stack[len(op_stack)-1]
		
		#find the precedence of the new operator over the current top operator
		has_precedence=op_precedence(active_op,new_op)
		
		#if this operator has precedence over the next operator in the stack, then add it to the result now
		if(has_precedence):
			out_acc+=active_op+' '
			op_stack=op_stack[0:len(op_stack)-1]
	
	#unconditionally add the new operator
	op_stack.append(new_op)
	
	return (out_acc,op_stack)

#is this character an operator?
def is_op(c):
	#parenthesis characters change order of operations and so also need operator status
	#boolean operators are also incuded
	return c=='^' or c=='*' or c=='/' or c=='%' or c=='+' or c=='-' or c=='(' or c==')' or c=='&&' or c=='||' or c=='~' or c=='>' or c=='<' or c=='='

#is this character valid as part of a number?
def is_numeric(c):
	return (c>='0' and c<='9') or c=='.'

#reads a token
def get_token(exp,i):
	#accumulate the token in here
	t=''
	while(i<len(exp)):
		t+=exp[i]
		
#		print('t='+t+', i='+str(i))
		
		#if we finished reading an operator, then return that operator
		if(is_op(t)):
			return t
		#if t is not an operator and there are characters left to read
		elif((i+1)<len(exp)):
			#if we're not in the middle of reading an operator
			if(len(t)>0 and t[0]!='&' and t[0]!='|'):
				#if the next character after this is an operator
				if(is_op(exp[i+1]) or exp[i+1]=='&' or exp[i+1]=='|'):
					#this is a number or symbol that we're now finished reading
					return t
		
		i+=1
	
	return t

#translate the infix expression (exp) into unambigious RPN based on operator precedence
def rpn_translate(exp):
	#remove spaces
	exp=exp.replace(' ','')
	
	#for a - which is not preceded by a number, precede it by 0 and put parens around the operation
	new_exp=''
	close_paren_cnt=0
	i=0
	while i<len(exp):
		if(exp[i]=='-'):
			if((i==0) or ((not is_numeric(exp[i-1])) and (exp[i-1]!=')'))):
				if(((i+1)<len(exp)) and (exp[i+1]=='-' or is_numeric(exp[i+1]))):
					new_exp+='(0'
					close_paren_cnt+=1
				else:
					new_exp+='0'
		elif(not is_numeric(exp[i])):
			if(i>0 and is_numeric(exp[i-1])):
				if(close_paren_cnt>0):
					new_exp+=')'
					close_paren_cnt-=1
		new_exp+=exp[i]
		i+=1
	while(close_paren_cnt>0):
		new_exp+=')'
		close_paren_cnt-=1
	
	print('Evaluating: '+new_exp) #debug
	
	exp=new_exp
	
	#the operator stack (appended to as we find operators)
	op_stack=[]
	
	#output accumulator; the string which will be returned
	out_acc=''
	
	#for each character of input
	i=0
	while(i<len(exp)):
		t=get_token(exp,i)
#		print('got token t='+t)
		
		if(t=='('):
			op_stack.append(t)
		elif(t==')'):
#			op_stack.append(exp[i])
			#pop off until a ( is found
			j=len(op_stack)-1
			while(j>=0 and op_stack[j]!='('):
#				out_acc,op_stack=add_op(out_acc,op_stack[0:len(op_stack)-1],op_stack[len(op_stack)-1])
				out_acc+=op_stack[j]+' '
				op_stack=op_stack[0:len(op_stack)-1]
				
				j-=1
			if(op_stack[j]=='('):
				op_stack=op_stack[0:len(op_stack)-1]
			
		elif(is_op(t)):
			out_acc,op_stack=add_op(out_acc,op_stack,t)
			
			last_char_op=True
		else:
			out_acc+=t
			out_acc+=' '
			
		
#		print('rpn_translate debug 0, out_acc='+out_acc+', op_stack='+str(op_stack))
		i+=len(t)
		
	#append any operators left in the op stack
	i=len(op_stack)-1
	while(i>=0):
		out_acc+=op_stack[i]+' '
		i-=1
	
	return out_acc

#evaluate the given space-delimited rpn expression
#if this expression contains variables or anything other than constants and operators
#then it will return a new simplified stack leaving those values untouched (i.e. variables are allowed)
def rpn_eval(rpn_exp,verbose=False):
	#the rpn stack (operators and operands)
	stack=[]
	
	token=''
	#for each character
	for i in range(0,len(rpn_exp)):
		#spaces delimit tokens, so stop and go to the next token
		if(rpn_exp[i]==' '):
			stack.append(token)
			token=''
			continue
		#if this wasn't a space then it's part of a token
		token+=rpn_exp[i]
	
	#if there was a token after the last space, then add it here
	if(token!=''):
		stack.append(token)
		token=''
	
#	print(stack)
	
	#go through the stack and make appropriate replacements
	i=0
	while (i<len(stack)):
		#if we hit an operator, then perform the appropriate action
		if(is_op(stack[i])):
#			print('found operator at index '+str(i)+', applying operator '+stack[i])
			
			try:
				#operands used for this operator
				operands=2
				
				#result of this operation
				tmp=0.0
				
				#addition
				if(stack[i]=='+'):
					tmp=float(stack[i-2])+float(stack[i-1])
				#subtraction
				elif(stack[i]=='-'):
					tmp=float(stack[i-2])-float(stack[i-1])
				#multiplication
				elif(stack[i]=='*'):
					tmp=float(stack[i-2])*float(stack[i-1])
				#division
				elif(stack[i]=='/'):
					if(float(stack[i-1])==0.0):
						if(verbose):
							print('Error: Could not divide by 0, returning stack')
						return stack
					tmp=float(stack[i-2])/float(stack[i-1])
				#modulo
				elif(stack[i]=='%'):
					tmp=int(stack[i-2])%int(stack[i-1])
				#exponent
				elif(stack[i]=='^'):
					tmp=pow(float(stack[i-2]),float(stack[i-1]))
				#boolean and
				elif(stack[i]=='&&'):
					tmp=1
					if(float(stack[i-2])==0.0):
						tmp=0
					elif(float(stack[i-1])==0.0):
						tmp=0
				#boolean or
				elif(stack[i]=='||'):
					tmp=0
					if(float(stack[i-2])!=0.0):
						tmp=1
					elif(float(stack[i-1])!=0.0):
						tmp=1
				#not
				elif(stack[i]=='~'):
					tmp=0
					if(float(stack[i-1])==0.0):
						tmp=1
					#~ is a unary operator
					operands=1
				#greater than
				elif(stack[i]=='>'):
					tmp=0
					if(float(stack[i-2])>float(stack[i-1])):
						tmp=1
				#less than
				elif(stack[i]=='<'):
					tmp=0
					if(float(stack[i-2])<float(stack[i-1])):
						tmp=1
				#equal to
				elif(stack[i]=='='):
					tmp=0
					if(stack[i-2]==stack[i-1]):
						tmp=1
				
				new_stack=stack[0:i-operands]
				new_stack.append(str(tmp))
				for j in range(i+1,len(stack)):
					new_stack.append(stack[j])
				stack=new_stack
				
	#			print('after applying operator stack='+str(stack))
				#we removed some items from the stack
				#so we need to back-track to where the next token is and not skip anything
				i-=2
			except (ValueError, IndexError):
#				print('Error: Could not convert stack objects to numbers, returning stack as-is')
#				return stack
				if(len(stack)>2):
					#if one of these operands was an operator then we can't continue (stack not simplified enough)
					if(is_op(stack[i-2]) or is_op(stack[i-1])):
						return stack
					if(verbose):
						print('Warning: Could not convert stack objects to numbers, skipping '+stack[i-2]+stack[i]+stack[i-1]+' operation...')
				else:
					if(verbose):
						print('Warning: Too few arguments, skipping '+stack[i]+' operation...')
			except ZeroDivisionError:
				if(verbose):
					print('Warning: Division by 0; skipping...')

		i+=1
	return stack


if(__name__=='__main__'):
	if(len(sys.argv)<2):
		print('This converts an infix math expression into an RPN version based on operator precedence rules and then evaluates it')
		print('The --noverbose option will cause only the last line (result or simplified expression) to be output')
		print("\t"+'this is useful in order to feed the output of this program into another program')
		print('Usage: '+sys.argv[0]+' [--noverbose] <infix math expression> [[variable=value] ... ]')
		sys.exit(1)

	#be verbose by default
	verbose=True
	if(sys.argv[1]=="--noverbose"):
		verbose=False
		sys.argv=sys.argv[1:]

	if(len(sys.argv)>2):
		for arg_idx in range(2,len(sys.argv)):
			var_def=sys.argv[arg_idx]
			
			var_name=''
			var_value=''
			
			read_name=True
			for i in range(0,len(var_def)):
				if(var_def[i]=='='):
					read_name=False
				elif(read_name):
					var_name+=var_def[i]
				else:
					var_value+=var_def[i]
			
			#do variable substitution in the original expression
			sys.argv[1]=sys.argv[1].replace(var_name,var_value)

	rpn_exp=rpn_translate(sys.argv[1])

	if(verbose):
		sys.stdout.write('original expression as rpn='+"\n\t")
		print(rpn_exp)
		print('')

	rpn_result=rpn_eval(rpn_exp,verbose)

	if(verbose):
		print('')

	if(not verbose):
		if(len(rpn_result)>1):
			for i in range(0,len(rpn_result)):
				sys.stdout.write(rpn_result[i]+' ')
			print('')
		else:
			print(rpn_result[0])
	else:
		if(len(rpn_result)>1):
			sys.stdout.write('simplified expression='+"\n\t")
			for i in range(0,len(rpn_result)):
				sys.stdout.write(rpn_result[i]+' ')
			print('')
		elif(len(rpn_result)>0):
			print('result='+"\n\t"+rpn_result[0])

