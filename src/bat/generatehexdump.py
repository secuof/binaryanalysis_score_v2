#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2012-2016 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
This is a plugin for the Binary Analysis Tool. It takes the output of hexdump -Cv
and writes it to a file with gzip compression. The output is later used in the
graphical user interface.

Parameters:

BAT_REPORTDIR :: directory where output should be written to. This is useful for caching
BAT_IMAGE_MAXFILESIZE :: maximum size of source file

This should be run as a postrun scan
'''

import os, os.path, sys, subprocess, gzip

def generateHexdump(filename, unpackreport, scantempdir, topleveldir, scanenv, cursor, conn, debug=False):
	if not 'checksum' in unpackreport:
		return
	reportdir = scanenv.get('BAT_REPORTDIR', '.')
	try:
		os.stat(reportdir)
	except:
		## BAT_REPORTDIR does not exist
		try:
			os.makedirs(reportdir)
		except Exception, e:
			return

	maxsize = int(scanenv.get('BAT_IMAGE_MAXFILESIZE', sys.maxint))
	## override file name, we won't use it much
	filename = os.path.join(unpackreport['realpath'], unpackreport['name'])
	filesize = os.stat(filename).st_size
	if filesize > maxsize:
		return
	if not os.path.exists("%s/%s-hexdump.gz" % (reportdir, unpackreport['checksum'])):
		p = subprocess.Popen(['hexdump', '-Cv', filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
		(stanout, stanerr) = p.communicate()
		if stanout != "":
			gf = gzip.open("%s/%s-hexdump.gz" % (reportdir, unpackreport['checksum']), 'w')
			gf.write(stanout)
			gf.close()
