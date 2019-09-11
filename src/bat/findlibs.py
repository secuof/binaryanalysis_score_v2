#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2012-2016 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

import os, os.path, sys, subprocess, copy, cPickle, multiprocessing, pydot
import bat.interfaces
import elfcheck

'''
This program can be used to check whether the dependencies of a dynamically
linked executable or library can be satisfied at runtime given the libraries
in a scanned archive.

For this the correct dynamic libraries for an executable and for other libraries
need to be found. There might be more than one copy or version for a particular
library since there could for example be multiple file systems inside a firmware.
It is hard to find out what the actual state at runtime might possibly be because
it might be unknown how the dynamic linker is configured, or which file systems
are mounted where and when. Although in the vast majority of cases it is crystal
clear which libraries are used sometimes it can get tricky.

The following needs to be done:

* verify the architectures of the dependencies are compatible with the
executable or library.
* handle symlinks, since not the fully qualified file name might have been
used in the binary, but the name of a symlink was used.
* multiple copies of (possibly conflicting) libraries need to be dealt with
properly.

Something similar is done for remote and local variables.

Then symbols need to be resolved in a few steps (both for functions and
variables):

1. for each undefined symbol in a file see if it is defined in one of the
declared dependencies as GLOBAL.
2. for each weak undefined symbol in a file see if it is defined in one of the
declared dependencies as GLOBAL.
3. for each undefined symbol in a file that has not been resolved yet see if it
is defined in one of the declared dependencies as WEAK.
4. for each defined weak symbol in a file see if one of the declared
dependencies defines the same symbols as GLOBAL.

Symbolic links can be a challenge as well if they point to locations that are
only known at run time, for example other file systems that are mounted. Since
BAT will not unpack these in the same locations as where they are supposed to be
mounted some links might not resolve properly.
'''

## helper function to find if names can be found in known interfaces
## such as POSIX, SuS, LSB, and so on
def knownInterface(names, ptype):
	if ptype == 'functions':
		for i in names:
			if i not in bat.interfaces.allfunctions:
				return False
	elif ptype == 'variables':
		for i in names:
			if i not in bat.interfaces.allvars:
				return False
	return True

## generate PNG files and optionally SVG files of the graph
def writeGraph((elfgraph, filehash, imagedir, generatesvg)):
	elfgraph_tmp = pydot.graph_from_dot_data(elfgraph)
	if type(elfgraph_tmp) == list:
		if len(elfgraph_tmp) == 1:
			elfgraph_tmp[0].write_png(os.path.join(imagedir, '%s-graph.png' % filehash))
			if generatesvg:
				elfgraph_tmp[0].write_svg(os.path.join(imagedir, '%s-graph.svg' % filehash))
	else:
		elfgraph_tmp.write_png(os.path.join(imagedir, '%s-graph.png' % filehash))
		if generatesvg:
			elfgraph_tmp.write_svg(os.path.join(imagedir, '%s-graph.svg' % filehash))

## store variable names, function names from the ELF file
## along with the type, and so on. Also store the soname for
## the ELF file, as well as any RPATH values that might have
## been defined.
def extractfromelf((filepath, filename)):
	remotefuncs = set()
	localfuncs = set()
	remotevars = set()
	localvars = set()
	rpaths = set()
	weakremotevars = set()
	weakremotefuncs = set()
	weaklocalvars = set()
	weaklocalfuncs = set()
	elfsonames = set()
	elftype = ""

	elfres = elfcheck.getAllSymbols(os.path.join(filepath, filename))
	if elfres == None:
		return

	## a list of variable names to ignore.
	varignores = ['__dl_ldso__']

	for s in elfres:
		if not s['type'] in ['func', 'object','ifunc']:
			continue

		## then split into local and global symbols
		if s['section'] != 0:
			if s['type'] in ['func', 'ifunc']:
				if s['binding'] == 'weak':
					weaklocalfuncs.add(s['name'])
				else:
					localfuncs.add(s['name'])
			else:
				## no ABS values
				if s['section'] == 0xfff1:
					continue
				if s['name'] in varignores:
					continue
				if s['binding'] == 'weak':
					weaklocalvars.add(s['name'])
				else:
					localvars.add(s['name'])
		else:
			if s['type'] in ['func', 'ifunc']:
				## See http://gcc.gnu.org/ml/gcc/2002-06/msg00112.html
				if s['name'] == '_Jv_RegisterClasses':
					continue
				if s['binding'] == 'weak':
					weakremotefuncs.add(s['name'])
				else:
					remotefuncs.add(s['name'])
			else:
				## no ABS values
				if s['section'] == 0xfff1:
					continue
				if s['binding'] == 'weak':
					weakremotevars.add(s['name'])
				else:
					remotevars.add(s['name'])

	elfres = elfcheck.getDynamicLibs(os.path.join(filepath, filename))

	if elfres == None:
		return

	if 'rpath' in elfres:
		rpaths = elfres['rpath'].split(':')

	if 'sonames' in elfres:
		elfsonames = set(elfres['sonames'])

	(totalelf, elfres) = elfcheck.parseELF(os.path.join(filepath, filename))
	if not totalelf:
		return

	return (filename, list(localfuncs), list(remotefuncs), list(localvars), list(remotevars), list(weaklocalfuncs), list(weakremotefuncs), list(weaklocalvars), list(weakremotevars), elfsonames, elfres['elftype'], rpaths)

## The entry point for this module.
def findlibs(unpackreports, scantempdir, topleveldir, processors, scanenv, batcursors, batcons, scandebug=False, unpacktempdir=None):
	## crude check for broken PyDot
	if pydot.__version__ == '1.0.3' or pydot.__version__ == '1.0.2':
		return
	if 'overridedir' in scanenv:
		try:
			del scanenv['BAT_IMAGEDIR']
		except: 
			pass

	imagedir = scanenv.get('BAT_IMAGEDIR', os.path.join(topleveldir, "images"))
	try:
		os.stat(imagedir)
	except:
		## BAT_IMAGEDIR does not exist
		try:
			os.makedirs(imagedir)
		except Exception, e:
			return

	## by default SVG representations of the graphs are not
	## generated unless explicitely enabled.
	generatesvg = False
	if scanenv.get('ELF_SVG', '0') == '1':
		generatesvg = True

	## store names of all ELF files present in scan archive
	elffiles = set()

	## There are situations when it is not clear which library to look at.
	## Examples are:
	## * files that are normally symlinks, but have been copied into
	##   a file system that does not support symlinks
	## * rescue file systems in a firmware that contain the same, or
	##   similar (partial) content as the main image
	## Sometimes it will only be apparent at run time which files
	## really are linked with eachother.
	##
	## Therefore we need the keep a list of file names to their
	## full paths in the scan archive.
	##
	## For example, libm.so.0 could map to lib/libm.so.0 and lib2/libm.so.0
	## libraryname -> [list of libraries]
	squashedelffiles = {}

	## cache the names of local and remote functions and variables,
	## both normal and weak
	localfunctionnames = {}
	remotefunctionnames = {}
	localvariablenames = {}
	remotevariablenames = {}
	weaklocalfunctionnames = {}
	weakremotefunctionnames = {}
	weaklocalvariablenames = {}
	weakremotevariablenames = {}

	## a list of unresolvable files: they don't exist on the system
	## One situation in where this is possible is if the archive
	## that is scanned does not include all dependencies. Example:
	## a single binary, or a firmware update that surgically replaces
	## parts on a device.
	unresolvable = []

	## Frequently programs do not record the name of the library, but instead
	## use the name of a symbolic link that points to the library. To correctly
	## resolve symbols from the libraries these symbolic links point to the
	## correct library first has to be found. This can be a multistep process if
	## symbolic links point to other files that are symbolic links themselves.
	## Symbolic links could be absolute links or relative paths. Absolute paths first
	## have to be converted into paths relative to the root of the firmware, so they
	## do not point to files in the host system, which could possibly contaminate
	## results.
	##
	## Store all symlinks in the scan archive that point to ELF files (as far as
	## can be determined)
	symlinks = {}
	symlinklinks = {}
	scantempdirlen = len(scantempdir)
	for i in unpackreports:
		if not 'checksum' in unpackreports[i]:
			if 'tags' in unpackreports[i]:
				store = False
				if 'symlink' in unpackreports[i]['tags']:
					target = os.readlink(os.path.join(scantempdir, i))

					if os.path.isabs(target):
						## the target points to an absolute path. Try to find
						## the file relative to the root of the file system or
						## compressed file.
						relscanpathlen = len(unpackreports[i]['path'])
						reltarget = os.path.relpath(target, '/')
						linkpath = os.path.join(unpackreports[i]['realpath'][:-relscanpathlen], reltarget)
						if os.path.islink(linkpath):
							symlinklinks[i] = linkpath[scantempdirlen:]
							continue
						if os.path.exists(linkpath):
							store = True
					else:
						## the target points to a relative path.
						## Two situations: starting in the same directory, or
						## pointing to a different directory
						if target.startswith('..'):
							relscanpathlen = len(unpackreports[i]['path'])
							reltarget = os.path.join(unpackreports[i]['path'], target)
							linkpath = os.path.join(unpackreports[i]['realpath'], target)
							if os.path.islink(linkpath):
								symlinklinks[i] = os.path.normpath(linkpath[scantempdirlen:])
								continue
							if os.path.exists(linkpath):
								relscanpathlen = len(unpackreports[i]['path'])
								reltarget = os.path.normpath(reltarget)
								linkpath = os.path.normpath(linkpath)
								target = reltarget
								store = True
						else:
							linkpath = os.path.join(unpackreports[i]['realpath'], target)
							if os.path.islink(linkpath):
								symlinklinks[i] = linkpath[scantempdirlen:]
								continue
							if os.path.exists(linkpath):
								relscanpathlen = len(unpackreports[i]['path'])
								target = os.path.join(unpackreports[i]['realpath'][-relscanpathlen:], target)
								store = True
					if store:
						if symlinks.has_key(os.path.basename(i)):
							symlinks[os.path.basename(i)].append({'original': i, 'target': target, 'absolutetargetpath': linkpath[scantempdirlen+1:]})
						else:
							symlinks[os.path.basename(i)] = [{'original': i, 'target': target, 'absolutetargetpath': linkpath[scantempdirlen+1:]}]
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

		if not squashedelffiles.has_key(os.path.basename(i)):
			squashedelffiles[os.path.basename(i)] = [i]
		else:
			squashedelffiles[os.path.basename(i)].append(i)
		elffiles.add(i)

	if len(elffiles) == 0:
		return

	## there could be symlinks that point to other symlinks
	if len(symlinklinks) != 0:
		resolving = True
		while len(symlinklinks) != 0 and resolving:
			symlinklinksnew = copy.deepcopy(symlinklinks)
			resolving = False
			for s in symlinklinks:
				sll = symlinklinks[s]
				if os.path.basename(sll) in symlinks:
					if len(symlinks[os.path.basename(sll)]) == 1:
						target = symlinks[os.path.basename(sll)][0]['target']
						absolutepath = symlinks[os.path.basename(sll)][0]['absolutetargetpath']
						symlinks[os.path.basename(s)] = [{'original': s, 'target': target, 'absolutetargetpath': absolutepath}]
						del symlinklinksnew[s]
						resolving = True
			symlinklinks = symlinklinksnew

	## Then map the function names to libraries that define them. For this two
	## mappings from function names to libraries are kept, one for "regular"
	## functions, one for "weak" functions.
	funcstolibs = {}
	weakfuncstolibs = {}

	## Map sonames to libraries. For each soname a list of files that define the
	## soname is kept.
	sonames = {}

	## a list of variable names to ignore.
	varignores = ['__dl_ldso__']

	## Store all local (defined) and remote function names (undefined and needed)
	## for each dynamic ELF executable or library on the system.

	pool = multiprocessing.Pool(processes=processors)
	elftasks = map(lambda x: (scantempdir, x), elffiles)
	elfres = pool.map(extractfromelf, elftasks)
	pool.terminate()

	elftypes = {}
	rpaths = {}

	for i in elfres:
		if i == None:
			continue
		(filename, localfuncs, remotefuncs, localvars, remotevars, weaklocalfuncs, weakremotefuncs, weaklocalvars, weakremotevars, elfsonames, elftype, elfrpaths) = i
		if elfrpaths != []:
			rpaths[filename] = elfrpaths
		for soname in elfsonames:
			if soname in sonames:
				sonames[soname].append(filename)
			else:
				sonames[soname] = [filename]
		for funcname in localfuncs:
			if funcname in funcstolibs:
				funcstolibs[funcname].append(filename)
			else:
				funcstolibs[funcname] = [filename]
		for funcname in weaklocalfuncs:
			if funcname in weakfuncstolibs:
				weakfuncstolibs[funcname].append(filename)
			else:
				weakfuncstolibs[funcname] = [filename]

		## store normal remote and local functions and variables ...
		localfunctionnames[filename] = localfuncs
		remotefunctionnames[filename] = remotefuncs
		localvariablenames[filename] = localvars
		remotevariablenames[filename] = remotevars

		## ... as well as the weak ones
		weaklocalfunctionnames[filename] = weaklocalfuncs
		weakremotefunctionnames[filename] = weakremotefuncs
		weaklocalvariablenames[filename] = weaklocalvars
		weakremotevariablenames[filename] = weakremotevars

		## record per ELF file what kind of ELF file it is
		elftypes[filename] = elftype

	## For each file keep a list of other files that use this file. This is mostly
	## for reporting.
	usedby = {}
	usedlibsperfile = {}
	usedlibsandcountperfile = {}
	unusedlibsperfile = {}
	possiblyusedlibsperfile = {}
	plugins = {}
	pluginsperexecutable = {}

	notfoundfuncsperfile = {}
	notfoundvarssperfile = {}

	## Keep a list of files that are identical, for example copies of libraries
	dupes = {}

	## grab and store the architecture of each file. Files should have
	## the same architecture, or, at least the same base architecture or they cannot
	## have been linked with eachother (example: ARM and MIPS files cannot be
	## linked with eachother)
	architectures = {}
	for i in elffiles:
		if not i in elftypes:
			continue
		if elftypes[i] == 'elfrelocatable':
			continue
		filehash = unpackreports[i]['checksum']
		leaf_file = open(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash), 'rb')
		leafreports = cPickle.load(leaf_file)
		leaf_file.close()

		if not 'architecture' in leafreports:
			continue

		architectures[i] = leafreports['architecture']

	## A list of functions to ignore (is this correct???)
	ignorefuncs = set(["__ashldi3", "__ashrdi3", "__cmpdi2", "__divdi3", "__fixdfdi", "__fixsfdi", "__fixunsdfdi", "__fixunssfdi", "__floatdidf", "__floatdisf", "__floatundidf", "__lshrdi3", "__moddi3", "__ucmpdi2", "__udivdi3", "__umoddi3", "main"])
	for i in elffiles:
		if not i in elftypes:
			continue
		if elftypes[i] == 'elfrelocatable':
			continue
		## per ELF file keep lists of used libraries and libraries that are possibly
		## used.
		## The later is searched if it needs to be guessed which libraries were
		## actually used.
		usedlibs = []
		possiblyused = []
		plugsinto = []

		filehash = unpackreports[i]['checksum']

		leaf_file = open(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash), 'rb')
		leafreports = cPickle.load(leaf_file)
		leaf_file.close()

		if remotefunctionnames[i] == [] and remotevariablenames[i] == [] and weakremotefunctionnames == [] and weakremotevariablenames == []:
			## nothing to resolve, so continue
			continue
		## keep copies of the original data
		remotefuncswc = copy.copy(remotefunctionnames[i])
		remotevarswc = copy.copy(remotevariablenames[i])

		funcsfound = []
		varsfound = []
		filteredlibs = []

		## reverse mapping
		filteredlookup = {}
		if leafreports.has_key('libs'):
			for l in leafreports['libs']:

				## temporary storage to hold the names of the libraries
				## searched for. This list will be manipulated later on.
				filtersquash = []

				if not squashedelffiles.has_key(l):
					## No library (or libraries) with the name that has been declared
					## in the ELF file can be found. It could be because the
					## declared name is actually a symbolic link that could, or could
					## not be present on the system.
					if not symlinks.has_key(l):
						## There are no symlinks that point to a library that's needed.
						## There could be various reasons for this, such as a missing
						## symlink that was not created during unpacking.
						if not sonames.has_key(l):
							unresolvable.append(l)
							continue
						if len(sonames[l]) != 1:
							## TODO: more libraries could possibly
							## fullfill the dependency.
							unresolvable.append(l)
							continue
						possiblyused.append(sonames[l][0])
						filtersquash = filtersquash + squashedelffiles[os.path.basename(sonames[l][0])]
					else:
						## there are one or possibly more symlinks that can fullfill
						## this requirement
						for sl in symlinks[l]:
							if sl['target'].startswith('/'):
								target = sl['absolutetargetpath']
							else:
								target = os.path.normpath(os.path.join(os.path.dirname(sl['original']), sl['target']))
								## TODO: verify if any of the links are symlinks
								## themselves. Add a safety mechanism for cyclical
								## symlinks.
								if os.path.islink(target):
									pass
								## add all resolved symlinks to the list of
								## libraries to consider
							filtersquash.append(target)
				else:
					filtersquash = squashedelffiles[l]

				## verify that the architectures are actually the same.
				## TODO: verify that this actually works. It could be that older binaries are
				## copied around and keep lingering for many years.
				#filtersquash = map(lambda x: architectures[f] == architectures[i], filtersquash)

				## now walk through the possible files that can resolve this dependency.
				## First verify how many possible files are in 'filtersquash' have.
				## In the common case this will be just one and then everything is easy.
				## Since there might be multiple files that satisfy a dependency (because
				## they have the same name) a few verification steps have to be taken.
				## Quite often the copies will be the same as well, which is easy to check using:
				## * SHA256 checksums
				## * equivalent local and remote function names (and in the future localvars and remotevars)
				if len(filtersquash) > 1:
					if len(set(map(lambda x: unpackreports[x]['checksum'], filtersquash))) == 1:
						filtersquash = [filtersquash[0]]
						## store duplicates for later reporting of alternatives
						dupes[filtersquash[0]] = filtersquash
					else:
						difference = False
						## compare the local and remote funcs and vars. If they
						## are equivalent they can be treated as if they were identical
						for f1 in filtersquash:
							if difference == True:
								break
							for f2 in filtersquash:
								if len(set(localfunctionnames[f1]).intersection(set(localfunctionnames[f2]))) == len(localfunctionnames[f1]):
									difference = True
									break
								if len(set(remotefunctionnames[f1]).intersection(set(remotefunctionnames[f2]))) != len(remotefunctionnames[f1]):
									difference = True
									break
						if not difference:
							dupes[filtersquash[0]] = filtersquash
							filtersquash = [filtersquash[0]]
				if len(filtersquash) == 1:
					filteredlibs += filtersquash
					if filteredlookup.has_key(filtersquash[0]):
						filteredlookup[filtersquash[0]].append(l)
					else:
						filteredlookup[filtersquash[0]] = [l]
					if remotefuncswc != []:
						if localfunctionnames.has_key(filtersquash[0]):
							## easy case
							localfuncsfound = list(set(remotefuncswc).intersection(set(localfunctionnames[filtersquash[0]])))
							if localfuncsfound != []:
								if usedby.has_key(filtersquash[0]):
									usedby[filtersquash[0]].append(i)
								else:
									usedby[filtersquash[0]] = [i]
								knowninterface = knownInterface(localfuncsfound, 'functions')
								usedlibs.append((l,len(localfuncsfound), knowninterface, 'functions'))
							funcsfound = funcsfound + localfuncsfound
							remotefuncswc = list(set(remotefuncswc).difference(set(funcsfound)))
					if remotevarswc != []:
						if localvariablenames.has_key(filtersquash[0]):
							localvarsfound = list(set(remotevarswc).intersection(set(localvariablenames[filtersquash[0]])))
							if localvarsfound != []:
								if usedby.has_key(filtersquash[0]):
									usedby[filtersquash[0]].append(i)
								else:
									usedby[filtersquash[0]] = [i]
								knowninterface = knownInterface(localvarsfound, 'variables')
								usedlibs.append((l,len(localvarsfound), knowninterface, 'variables'))
							varsfound = varsfound + localvarsfound
							remotevarswc = list(set(remotevarswc).difference(set(varsfound)))
				else:
					## TODO
					pass
			## normal resolving has finished, now resolve WEAK undefined symbols, first against
			## normal symbols ...
			weakremotefuncswc = copy.copy(weakremotefunctionnames[i])
			weakremotevarswc = copy.copy(weakremotevariablenames[i])
			for f in filteredlibs:
				if weakremotefuncswc != []:
					if localfunctionnames.has_key(f):
						## easy case
						localfuncsfound = list(set(weakremotefuncswc).intersection(set(localfunctionnames[f])))
						if localfuncsfound != []:
							if usedby.has_key(f):
								usedby[f].append(i)
							else:
								usedby[f] = [i]
							if len(filteredlookup[f]) == 1:
								knowninterface = knownInterface(localfuncsfound, 'functions')
								usedlibs.append((filteredlookup[f][0],len(localfuncsfound), knowninterface, 'functions'))
							else:
								## this should never happen
								pass
							funcsfound = funcsfound + localfuncsfound
							weakremotefuncswc = list(set(weakremotefuncswc).difference(set(funcsfound)))
				if weakremotevarswc != []:
					if localvariablenames.has_key(f):
						localvarsfound = list(set(weakremotevarswc).intersection(set(localvariablenames[filtersquash[0]])))
						if localvarsfound != []:
							if usedby.has_key(f):
								usedby[f].append(i)
							else:
								usedby[f] = [i]
							if len(filteredlookup[f]) == 1:
								knowninterface = knownInterface(localvarsfound, 'variables')
								usedlibs.append((filteredlookup[f][0],len(localvarsfound), knowninterface, 'variables'))
							else:
								## this should never happen
								pass
							varsfound = varsfound + localvarsfound
							weakremotevarswc = list(set(weakremotevarswc).difference(set(varsfound)))

			## then resolve normal unresolved symbols against weak symbols
			for f in filteredlibs:
				if remotefuncswc != []:
					if weaklocalfunctionnames.has_key(f):
						## easy case
						localfuncsfound = list(set(remotefuncswc).intersection(set(weaklocalfunctionnames[f])))
						if localfuncsfound != []:
							if usedby.has_key(f):
								usedby[f].append(i)
							else:
								usedby[f] = [i]
							if len(filteredlookup[f]) == 1:
								knowninterface = knownInterface(localfuncsfound, 'functions')
								usedlibs.append((filteredlookup[f][0],len(localfuncsfound), knowninterface, 'functions'))
							else:
								## this should never happen
								pass
							funcsfound = funcsfound + localfuncsfound
							remotefuncswc = list(set(remotefuncswc).difference(set(funcsfound)))
				if remotevarswc != []:
					if weaklocalvariablenames.has_key(f):
						localvarsfound = list(set(remotevarswc).intersection(set(weaklocalvariablenames[f])))
						if localvarsfound != []:
							if usedby.has_key(f):
								usedby[f].append(i)
							else:
								usedby[f] = [i]
							if len(filteredlookup[f]) == 1:
								knowninterface = knownInterface(localvarsfound, 'variables')
								usedlibs.append((filteredlookup[f][0],len(localvarsfound), knowninterface, 'variables'))
							else:
								## this should never happen
								pass
							varsfound = varsfound + localvarsfound
							remotevarswc = list(set(remotevarswc).difference(set(varsfound)))

			## finally check the weak local symbols and see if they have been defined somewhere
			## else as a global symbol. In that case the global symbol has preference.
			weaklocalfuncswc = copy.copy(weaklocalfunctionnames[i])
			weaklocalvarswc = copy.copy(weaklocalvariablenames[i])

			for f in filteredlibs:
				if weaklocalfuncswc != []:
					if localfunctionnames.has_key(f):
						localfuncsfound = list(set(weaklocalfuncswc).intersection(set(localfunctionnames[f])))
						if localfuncsfound != []:
							if usedby.has_key(f):
								usedby[f].append(i)
							else:
								usedby[f] = [i]
							if len(filteredlookup[f]) == 1:
								knowninterface = knownInterface(localfuncsfound, 'functions')
								usedlibs.append((filteredlookup[f][0],len(localfuncsfound), knowninterface, 'functions'))
							else:
								## this should never happen
								pass
							funcsfound = funcsfound + localfuncsfound

							weaklocalfuncswc = list(set(weaklocalfuncswc).difference(set(funcsfound)))
				if weaklocalvarswc != []:
					if localvariablenames.has_key(f):
						localvarsfound = list(set(weaklocalvarswc).intersection(set(localvariablenames[f])))
						if localvarsfound != []:
							if usedby.has_key(f):
								usedby[f].append(i)
							else:
								usedby[f] = [i]
							if len(filteredlookup[f]) == 1:
								knowninterface = knownInterface(localvarsfound, 'variables')
								usedlibs.append((filteredlookup[f][0],len(localvarsfound), knowninterface, 'variables'))
							else:
								## this should never happen
								pass
							varsfound = varsfound + localvarsfound
							weaklocalvarswc = list(set(weaklocalvarswc).difference(set(varsfound)))
			if remotevarswc != []:
				## TODO: find possible solutions for unresolved vars
				notfoundvarssperfile[i] = remotevarswc

			if remotefuncswc != []:
				## The scan has ended, but there are still symbols left.
				notfoundfuncsperfile[i] = remotefuncswc
				unusedlibs = list(set(leafreports['libs']).difference(set(map(lambda x: x[0], usedlibs))))
				unusedlibs.sort()
				unusedlibsperfile[i] = unusedlibs

				possiblesolutions = []

				## try to find solutions for the currently unresolved symbols.
				## 1. check if one of the existing used libraries already defines it as
				##    a WEAK symbol. If so, continue.
				## 2. check other libraries. If there is a match, store it as a possible
				##    solution.
				##
				## This could possibly be incorrect if an existing used library defines
				## the symbol as WEAK, but another "hidden" dependency has it as GLOBAL.
				## First for remote functions...
				for r in remotefuncswc:
					if r in ignorefuncs:
						continue
					if weakfuncstolibs.has_key(r):
						existing = False
						for w in weakfuncstolibs[r]:
							## TODO: update count if match was found
							if w in filteredlibs:
								existing = True
								break
						if not existing:
							possiblesolutions = possiblesolutions + weakfuncstolibs[r]
							#print >>sys.stderr, "NOT FOUND WEAK", r, weakfuncstolibs[r], filteredlibs
					elif funcstolibs.has_key(r):
						if len(funcstolibs[r]) == 1:
							## there are a few scenarions:
							## 1. the file is a plugin that is loaded into executables
							##    at run time.
							## 2. false positives.
							if elftypes[i] == 'elfdynamic':
								if list(set(map(lambda x: elftypes[x], funcstolibs[r]))) == ['elfexecutable']:
									plugsinto += funcstolibs[r]
							possiblesolutions = possiblesolutions + funcstolibs[r]
							continue
						else:
							found = False
							for l in funcstolibs[r]:
								if l in possiblesolutions:
									## prefer a dependency that is already used
									found = True
									break
							if not found:
								## there are a few scenarions:
								## 1. the file is a plugin that is loaded into executables
								##    at run time.
								## 2. false positives.
								if elftypes[i] == 'elfdynamic':
									if list(set(map(lambda x: elftypes[x], funcstolibs[r]))) == ['elfexecutable']:
										plugsinto += funcstolibs[r]
								## there are multiple files that can satisfy this dependency
								## 1. check if the files are identical (checksum)
								## 2. if identical, check for soname and choose the one
								## of which the name matches
								## 3. check if the files that implement the same thing are
								## libs or executables. Prefer libs.
								if len(set(map(lambda x: unpackreports[x]['checksum'], funcstolibs[r]))) == 1:
									for l in funcstolibs[r]:
										if sonames.has_key(os.path.basename(l)):
											found = True
											possiblesolutions.append(l)
											break
									if not found:
										pass
								else:
									pass
				## ... then for remote variables ...
				for r in remotevarswc:
					pass
				#print >>sys.stderr, "NOT FULLFILLED", i, remotefuncswc, remotevarswc, usedlibs
				if possiblesolutions != []:
					#print >>sys.stderr, "POSSIBLE LIBS TO SATISFY CONDITIONS", i, list(set(possiblesolutions))
					possiblyusedlibsperfile[i] = list(set(possiblesolutions))
			else:
				if set(leafreports['libs']).difference(set(map(lambda x: x[0], usedlibs))) != set():
					unusedlibs = list(set(leafreports['libs']).difference(set(map(lambda x: x[0], usedlibs))))
					unusedlibs.sort()
					unusedlibsperfile[i] = unusedlibs
					#print >>sys.stderr, "UNUSED LIBS", i, list(set(leafreports[i]['libs']).difference(set(usedlibs)))
					#print >>sys.stderr
			if possiblyused != []:
				pass
				#print >>sys.stderr, "POSSIBLY USED", i, possiblyused
				#print >>sys.stderr
		else:
			## there are files that are dynamically linked
			if elftypes[i] == 'elfdynamic':
				## if there are undefined references, then it is likely a plugin
				pass
		usedlibs_tmp = {}

		## combine the results from usedlibs for variable names and function names
		for l in usedlibs:
			(numberofsymbols, knowninterface) = l[1:-1]
			if usedlibs_tmp.has_key(l[0]):
				inposix = usedlibs_tmp[l[0]][1] and knowninterface
				usedlibs_tmp[l[0]] = (usedlibs_tmp[l[0]][0] + numberofsymbols, inposix)
			else:
				usedlibs_tmp[l[0]] = (l[1], l[2])

		## for each file get the list of libraries that are used
		if not usedlibsperfile.has_key(i):
			usedlibsp = list(set(map(lambda x: x[0], usedlibs)))
			usedlibsp.sort()
			usedlibsperfile[i] = usedlibsp

		## rework the data from usedlibs_tmp into a list of tuples
		## [(name of ELF file, amount of symbols, known interface)]
		if not usedlibsandcountperfile.has_key(i):
			usedlibsandcountperfile[i] = map(lambda x: (x[0],) + x[1], usedlibs_tmp.items())

		## store information about plugins
		if plugsinto != []:
			pcount = {}
			for p in plugsinto:
				if pcount.has_key(p):
					pcount[p] += 1
				else:
					pcount[p] = 1
			plugins[i] = pcount

	## store a list of possible plugins per executable
	for p in plugins:
		for pl in plugins[p]:
			if pl in pluginsperexecutable:
				pluginsperexecutable[pl].append(p)
			else:
				pluginsperexecutable[pl] = [p]

	## for each ELF file for which there are results write back the results to
	## 'leafreports'. Also update tags if the file is a plugin.
	for i in elffiles:
		if not i in elftypes:
			continue
		if elftypes[i] == 'elfrelocatable':
			continue
		writeback = False

		if i in plugins:
			unpackreports[i]['tags'].append('plugin')

		aggregatereturn = {}

		if usedby.has_key(i):
			aggregatereturn['elfusedby'] = list(set(usedby[i]))
			writeback = True
		if usedlibsperfile.has_key(i):
			aggregatereturn['elfused'] = usedlibsperfile[i]
			writeback = True
		if unusedlibsperfile.has_key(i):
			aggregatereturn['elfunused'] = unusedlibsperfile[i]
			writeback = True
		if notfoundfuncsperfile.has_key(i):
			aggregatereturn['notfoundfuncs'] = notfoundfuncsperfile[i]
			writeback = True
		if notfoundvarssperfile.has_key(i):
			aggregatereturn['notfoundvars'] = notfoundvarssperfile[i]
			writeback = True
		if possiblyusedlibsperfile.has_key(i):
			aggregatereturn['elfpossiblyused'] = possiblyusedlibsperfile[i]
			writeback = True

		## only write the new leafreport if there actually is something to write back
		if writeback:
			filehash = unpackreports[i]['checksum']
			leaf_file = open(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash), 'rb')
			leafreports = cPickle.load(leaf_file)
			leaf_file.close()

			for e in aggregatereturn:
				if aggregatereturn.has_key(e):
					leafreports[e] = copy.deepcopy(aggregatereturn[e])
			if i in plugins:
				leafreports['tags'].append('plugin')

			leaf_file = open(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash), 'wb')
			leafreports = cPickle.dump(leafreports, leaf_file)
			leaf_file.close()

	squashedgraph = {}
	for i in elffiles:
		if not i in elftypes:
			continue
		if elftypes[i] == 'elfrelocatable':
			continue
		libdeps = usedlibsandcountperfile[i]
		if not i in squashedgraph:
			squashedgraph[i] = []
		for d in libdeps:
			(dependency, amountofsymbols, knowninterface) = d
			if not squashedelffiles.has_key(dependency):
				if sonames.has_key(dependency):
					if len(sonames[dependency]) != 1:
						continue
					else:
						squashedgraph[i].append((sonames[dependency][0], amountofsymbols, knowninterface))
				else:
					continue
			else:
				if len(squashedelffiles[dependency]) != 1:
					pass
				else:
					squashedgraph[i].append((squashedelffiles[dependency][0], amountofsymbols, knowninterface))
		## TODO: wiggle possible plugins into the linking graph
		#if i in pluginsperexecutable:
		#	for p in pluginsperexecutable[i]:
		#		amountofsymbols = plugins[p][i]

	## TODO: make more parallel
	elfgraphs = set()
	for i in elffiles:
		if not i in elftypes:
			continue
		if elftypes[i] == 'elfrelocatable':
			continue
		if not i in squashedgraph:
			continue
		filehash = unpackreports[i]['checksum']
		ppname = os.path.join(unpackreports[i]['path'], unpackreports[i]['name'])
		seen = set()
		elfgraph = pydot.Dot(graph_type='digraph')
		if i in plugins:
			rootnode = pydot.Node(ppname, color='blue', style='dashed')
		else:
			rootnode = pydot.Node(ppname)
		elfgraph.add_node(rootnode)

		## processnodes is a tuple with 4 values:
		## (parent node, node text, count, nodetype)
		## 1. parent node: pointer to the parent node in the graph
		## 2. node text: text displayed in the node
		## 3. count: amount of links
		## 4. nodetype
		## Five types: normal knowninterface unused undeclared plugin
		## 1. used: the dependency is a normal dependency
		## 2. knowninterface: all used symbols are in a known standard
		## 3. unused: the dependency is not used
		## 4. undeclared: the dependency is used but undeclared
		## 5. plugin: the dependency is used as a plugin
		processnodes = set(map(lambda x: (rootnode,) + x + (True, True), squashedgraph[i]))
		newprocessNodes = set()
		for pr in processnodes:
			if pr[3] == True:
				newprocessNodes.add(pr[0:3] + ("knowninterface",))
			else:
				newprocessNodes.add(pr[0:3] + ("used",))
		processnodes = newprocessNodes
		if unusedlibsperfile.has_key(i):
			for j in unusedlibsperfile[i]:
				if not squashedelffiles.has_key(j):
					continue
				if len(squashedelffiles[j]) != 1:
					continue
				processnodes.add((rootnode, squashedelffiles[j][0], 0, "unused"))
				seen.add((i,j))
		if possiblyusedlibsperfile.has_key(i):
			for j in possiblyusedlibsperfile[i]:
				processnodes.add((rootnode, j, 0, "undeclared"))
				seen.add((i,j))
		seen.update(map(lambda x: (i, x[0]), squashedgraph[i]))

		while True:
			newprocessnodes = set()
			for j in processnodes:
				(parentnode, nodetext, count, nodetype) = j
				ppname = os.path.join(unpackreports[nodetext]['path'], unpackreports[nodetext]['name'])
				tmpnode = pydot.Node(ppname)
				elfgraph.add_node(tmpnode)
				if nodetype == "unused":
					## declared but unused dependencies are represented by dashed blue lines
					elfgraph.add_edge(pydot.Edge(parentnode, tmpnode, style='dashed', color='blue'))
				elif nodetype == "undeclared":
					## undeclared but used dependencies get a red solid line
					elfgraph.add_edge(pydot.Edge(parentnode, tmpnode, color='red'))
				elif nodetype == "knowninterface":
					elfgraph.add_edge(pydot.Edge(parentnode, tmpnode, style='dotted', label="%d" % count, labeldistance=1.5, labelfontsize=20.0))
				elif nodetype == "used":
					elfgraph.add_edge(pydot.Edge(parentnode, tmpnode, label="%d" % count, labeldistance=1.5, labelfontsize=20.0))

				if squashedgraph.has_key(nodetext):
					for n in squashedgraph[nodetext]:
						if not (nodetext, n[0]) in seen:
							if n[-1] == True:
								newprocessnodes.add((tmpnode,) +  n[0:-1] + ("knowninterface",))
							else:
								newprocessnodes.add((tmpnode,) +  n[0:-1] + ("used",))
							seen.add((nodetext, n[0]))
				if possiblyusedlibsperfile.has_key(nodetext):
					for u in possiblyusedlibsperfile[nodetext]:
						if not (nodetext, u) in seen:
							newprocessnodes.add((tmpnode, u, 0, "undeclared"))
							seen.add((nodetext, u))
				if unusedlibsperfile.has_key(nodetext):
					for u in unusedlibsperfile[nodetext]:
						if not (nodetext, u) in seen:
							if not squashedelffiles.has_key(u):
								continue
							if len(squashedelffiles[u]) != 1:
								continue
							newprocessnodes.add((tmpnode, squashedelffiles[u][0], 0, "unused"))
							seen.add((nodetext, u))
			processnodes = newprocessnodes
			if processnodes == set():
				break

		elfgraph_data = elfgraph.to_string()
		elfgraphs.add((elfgraph_data, filehash, imagedir, generatesvg))

	## finally generate pictures/SVG in parallel, in case there
	## are any graphs that need to be generated.
	if len(elfgraphs) != 0:
		pool = multiprocessing.Pool(processes=processors)
		elfres = pool.map(writeGraph, elfgraphs,1)
		pool.terminate()
