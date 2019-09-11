#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2009-2015 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
This file contains a few convenience functions that are used throughout the code.
'''

import string, re, subprocess, sys
from xml.dom import minidom

def isPrintables(lines):
	return len(lines) == len(filter(lambda x: x in string.printable, lines))

## check if a word is surrounded by NUL characters
def check_null(lines, offset, word):
        if lines[offset-1] == chr(0x00):
                if lines[offset+len(word)] == chr(0x00):
                        return True
        return False

## check if a word is surrounded by non-printable characters
def check_nonprintable(lines, offset, word):
        if lines[offset-1] not in string.printable:
                if lines[offset+len(word)] not in string.printable:
                        return True
        return False

## convenience method to check if the offset we find is in a blacklist
## Blacklists are composed of tuples (lower, upper) which mark a region
## in the parent file(!) as a no go area.
## This method returns the upperbound from the tuple for which
## lower <= offset < upper is True
def inblacklist(offset, blacklist):
	for bl in blacklist:
		if offset >= bl[0] and offset < bl[1]:
			return bl[1]

## convenience method to find the next lowest entry in the blacklist
def lowestnextblacklist(offset, blacklist):
	lowest = sys.maxint
	for bl in blacklist:
		if bl[0] > offset:
			if bl[0] < lowest:
				lowest = bl[0]
	if lowest == sys.maxint:
		return 0
	return lowest

###
## The helper method below is to specifically analyse Microsoft Windows binaries
## and extract the XML that can usually be found in those installers. Based on
## that information we might be able to get a better scan, since many well
## known installers have default values for the descriptive strings
###

## 1. search '<?xml'
## 2. search for '<assembly' open tag
## 3. search for </assembly> close tag
## 4. see if there is no junk in between (using XML parsing)
## 5. extract information from the assembly, such info from <assemblyIdentity>
##    like architecture and the packager that was used to pack and information
##    about dependencies
## 6. repeat, because there might be more than one XML assembly file included
##    (ignored for now)
## Returns a tuple with:
## * hash with name, version, architecture, platform
## * list of dependencies

def searchAssembly(filename, offsets, traileroffsets):
	exefile = open(filename, 'rb')
	assemblies = []
	lastsuccesstrailer = 0
	for offset in offsets:
		if offset < lastsuccesstrailer:
			continue
		for traileroffset in traileroffsets:
			if traileroffset < offset:
				continue
			exefile.seek(offset)
			assemblydata = exefile.read(traileroffset + 11 - offset)
			try:
				dom = minidom.parseString(assemblydata)
				assemblyNodes = dom.getElementsByTagName('assembly')
				if len(assemblyNodes) != 1:
					continue
				else:
					deps = []
					assemblyattrs = {}
					for ch in assemblyNodes[0].childNodes:
						if ch.localName == "assemblyIdentity":
							for attr in xrange(0, ch.attributes.length):
								assemblyattrs[ch.attributes.item(attr).name] = ch.attributes.item(attr).value
						if ch.localName == "dependency":
							assemblyId = ch.getElementsByTagName('assemblyIdentity')
							for assembly in assemblyId:
								depsattrs = {}
								for attr in xrange(0, assembly.attributes.length):
									depsattrs[assembly.attributes.item(attr).name] = assembly.attributes.item(attr).value
								deps.append(depsattrs)
					assemblies.append((assemblyattrs, deps))
					lastsuccesstrailer = traileroffset
					break
			except Exception, e:
				pass
	exefile.close()
	return assemblies

## used in unpack scans
def searchAssemblyAttrs(filename, headeroffsets, traileroffsets):
	res = searchAssembly(filename, headeroffsets, traileroffsets)
	if res != None:
		return map(lambda x: x[0], filter(lambda x: x[0] != {}, res))
	return []


## used in leaf scans
def searchAssemblyDeps(filename, headeroffsets, traileroffsets):
	res = searchAssembly(filename, headeroffsets, traileroffsets)
	if res != None:
		return map(lambda x: x[1], res)
	return {}

## Extract strings using xgettext. Apparently this does not always work correctly. For example for busybox 1.6.1:
## $ xgettext -a -o - fdisk.c
##  xgettext: Non-ASCII string at fdisk.c:203.
##  Please specify the source encoding through --from-code.
## We fix this by rerunning xgettext with --from-code=utf-8
## The results might not be perfect, but they are acceptable.
def extractStrings(filename, filedir):
	results = []
	p1 = subprocess.Popen(['xgettext', '-a', "--omit-header", "--no-wrap", "%s/%s" % (filedir, filename), '-o', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
	(stanout, stanerr) = p1.communicate()
	if p1.returncode != 0:
		## analyze stderr first
		if "Non-ASCII" in stanerr:
			## rerun xgettext with a different encoding
			p2 = subprocess.Popen(['xgettext', '-a', "--omit-header", "--no-wrap", "--from-code=utf-8", "%s/%s" % (filedir, filename), '-o', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
			## overwrite stanout
			(stanout, pstanerr) = p2.communicate()
			if p2.returncode != 0:
				return results
	source = stanout 
	lines = []
	linenumbers = []

	## escape just once to speed up extraction of filenumbers
	filename_escape = re.escape(filename)

	for l in stanout.split("\n"):
		## skip comments and hints
		if l.startswith("#, "):
			continue
		if l.startswith("#: "):
			## there can actually be more than one entry on a single line
			res = re.findall("%s:(\d+)" % (filename_escape,), l[3:])
			if res != None:
				linenumbers = linenumbers + map(lambda x: int(x), res)
			else:
				linenumbers.append(0)

		if l.startswith("msgid "):
			lines = []
			lines.append(l[7:-1])
		## when we see msgstr "" we have reached the end of a block and we can start
		## processing
		elif l.startswith("msgstr \"\""):
			count = len(linenumbers)
			for xline in lines:
				## split at \r
				## TODO: handle \0 (although xgettext will not scan any further when encountering a \0 in a string)
				for line in xline.split("\\r\\n"):
					for sline in line.split("\\n"):
						## do we really need this?
						sline = sline.replace("\\\n", "")

						## unescape a few values
						sline = sline.replace("\\\"", "\"")
						sline = sline.replace("\\t", "\t")
						sline = sline.replace("\\\\", "\\")
	
						## we don't want to store empty strings, they won't show up in binaries
						## but they do make the database a lot larger
						if sline == '':
							continue
						for i in range(0, len(linenumbers)):
							results.append((sline, linenumbers[i]))
			linenumbers = []
		## the other strings are added to the list of strings we need to process
		else:
			lines.append(l[1:-1])
	return results
