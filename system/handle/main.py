def hello(msg):
	return 'Hello ' + msg + ' world!'
	
def execute(command):
	import subprocess as sub
	p = sub.Popen(command,stdout=sub.PIPE,stderr=sub.PIPE)
	output, errors = p.communicate()
	output = output.split('\n')
	return output
