def hello(msg, window=None, browser=None):
	return 'Hello ' + msg + ' world!'
	
def execute(command, gtk=None, window=None, browser=None, json=None):
	print 'omg'
	print window.get_position()
	import subprocess as sub
	p = sub.Popen(command,stdout=sub.PIPE,stderr=sub.PIPE)
	output, errors = p.communicate()
	output = output.split('\n')
	return output
