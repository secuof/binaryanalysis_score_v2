#!/usr/bin/python
#-*- coding: utf-8 -*-

## Binary Analysis Tool
## Copyright 2014-2016 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

import os, os.path, sys, subprocess, copy, cPickle, elfcheck

'''
During scanning BAT tags duplicate files (same checksums) and only processes a
single file later on. Which file is marked as the 'original' and which as the
duplicate depends on the scanning order, which is non-deterministic.

In some situations there is more information available to make a better choice
about the 'original' and the duplicate.

This module is to fix these situations.

1. In ELF shared libraries the SONAME and RPATH attributes can be used.
'''

def fixduplicates(unpackreports, scantempdir, topleveldir, processors, scanenv, batcursors, batcons, scandebug=False, unpacktempdir=None):
	## First deal with ELF files
	## store names of all ELF files present in scan archive
	elffiles = set()
	dupefiles = set()

	seendupe = False

	for i in unpackreports:
		if not 'checksum' in unpackreports[i]:
			continue
		filehash = unpackreports[i]['checksum']
		if not os.path.exists(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash)):
			continue

		if not 'elf' in unpackreports[i]['tags']:
			continue

		## This makes no sense for for example statically linked libraries and, Linux kernel
		## images and Linux kernel modules, so skip.
		if 'static' in unpackreports[i]['tags']:
			continue
		if 'linuxkernel' in unpackreports[i]['tags']:
			continue
		if 'duplicate' in unpackreports[i]['tags']:
			seendupe = True
			dupefiles.add(i)
		else:
			elffiles.add(i)

	## only process if there actually are duplicate files
	if seendupe:
		dupehashes = {}
		for i in dupefiles:
			filehash = unpackreports[i]['checksum']
			if filehash in dupehashes:
				dupehashes[filehash].append(i)
			else:
				dupehashes[filehash] = [i]
		dupekeys = dupehashes.keys()
		for i in elffiles:
			filehash = unpackreports[i]['checksum']
			if filehash in dupekeys:
				realpath = unpackreports[i]['realpath']
				filename = unpackreports[i]['name']

				elfres = elfcheck.getDynamicLibs(os.path.join(realpath, filename))
				if elfres == {} or elfres == None:
					continue

				if not 'sonames' in elfres:
					continue

				sonames = elfres['sonames']

				## there should be only one SONAME
				if len(sonames) != 1:
					continue

				soname = sonames[0]
				if soname == filename:
					## no need for fixing
					continue
				if unpackreports[i]['scans'] != []:
					## if any unpack scans were successful then renaming might have
					## to be done recursively which needs more thought
					continue
				unpackreports[i]['tags'].append('duplicate')
				for j in dupehashes[filehash]:
					if soname == os.path.basename(j):
						unpackreports[j]['tags'].remove('duplicate')
						break
