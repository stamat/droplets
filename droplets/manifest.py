import os,json

class Manifest:
	dict = None
	path = None
	mandatory = []

	def load_manifest(self, path):
		mfile = open(path, 'r')
		#TODO: TRY EXCEPT
		manifest = json.loads(mfile.read())
		mfile.close()
		return manifest
	
	def dump_manifest(self, path):
		mfile = open(path, 'w')
		#TODO: TRY EXCEPT
		mfile.write(json.dumps(self.dict, indent=4))
		mfile.close()

	def __init__(self, path):
		self.setattribs(self.load_manifest('manifest_pattern'))
		manifest = self.load_manifest(path)
		self.path = path	
		self.dict = manifest
		self.apply_values(manifest)
	
	def set(self, key, value):
		setattr(self, key, value)
		self.dict[key] = value
	
	def setattribs(self, pattern):
		for key, value in pattern.iteritems():
			setattr(self.__class__, key, value[0])
			if value[1] == 1:
				self.mandatory.append(key)
		
	def apply_values(self, manifest):
		for key, value in manifest.iteritems():
			setattr(self, key, value)
			i = 0
			for v in self.mandatory:
				if v == key:
					self.mandatory.pop(i)
				i += 1
				
		if len(self.mandatory) == 0:
			return True
		else:
			print 'Manifest mandatory fields: '+str(self.mandatory)+', were not supplied. Please check your manifest file'
			raise SystemExit
