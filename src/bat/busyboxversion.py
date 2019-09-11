#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2009-2015 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

## Stand alone module to determine the version of BusyBox. Has a method for being called
## from one of the default scans, but can also be invoked separately.

import sys, os, tempfile, copy
from optparse import OptionParser
import busybox, extractor

def busybox_version(filename, tags, cursor, conn, filehashes, blacklist=[], scanenv={}, scandebug=False, unpacktempdir=None):
	try:
                filesize = os.stat(filename).st_size
		## if the whole file is blacklisted, we don't have to scan
		if blacklist != []:
                	if extractor.inblacklist(0, blacklist) == filesize:
				return None
			## make a copy and add a bogus value for the last
			## byte to a temporary blacklist to make the loop work
			## well.
			blacklist_tmp = copy.deepcopy(blacklist)
			blacklist_tmp.append((filesize,filesize))
			datafile = open(filename, 'rb')
			lastindex = 0
			datafile.seek(lastindex)
			for i in blacklist_tmp:
				if i[0] == lastindex:
					lastindex = i[1] - 1
					datafile.seek(lastindex)
					continue
				if i[0] > lastindex:
					## check if there actually is enough data to do a search first
					## "BusyBox v" has length 9, has at least 2 digits and a dot
					if (i[0] - lastindex) < 12:
						lastindex = i[1] - 1
						datafile.seek(lastindex)
						continue
					data = datafile.read(i[0] - lastindex)
					tmpfile = tempfile.mkstemp()
					os.write(tmpfile[0], data)
					os.fdopen(tmpfile[0]).close()
					bbres = busybox.extract_version(tmpfile[1])
					os.unlink(tmpfile[1])
					## set lastindex to the next
					lastindex = i[1] - 1
					datafile.seek(lastindex)
					if bbres != None:
						break
			datafile.close()
		else:
			bbres = busybox.extract_version(filename)
		if bbres != None:
			return (['busybox'], bbres)
	except Exception, e:
		return None

def main(argv):
	parser = OptionParser()
	parser.add_option("-b", "--binary", dest="bb", help="path to BusyBox binary", metavar="FILE")
	(options, args) = parser.parse_args()
	if options.bb == None:
		parser.error("Path to BusyBox binary needed")
	(res, version) = busybox_version(options.bb, None, None, {}, [])

	if version != None:
		print version
	else:
		print "No BusyBox found"

if __name__ == "__main__":
        main(sys.argv)
