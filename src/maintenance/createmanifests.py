#!/usr/bin/python
# -*- coding: utf-8 -*-

## Binary Analysis Tool
## Copyright 2014-2015 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
Program to process a whole directory full of compressed source code archives
to create simple manifest files that list checksums of every individual file
in an archive. This is to speed up scanning of archives when rebuilding the
BAT database.

Needs a file LIST in the directory it is passed as a parameter, which has the
following format:

package version filename origin

separated by whitespace

Compression is determined using magic
'''

import sys, os, magic, string, re, subprocess, shutil, stat
import tempfile, bz2, tarfile, gzip, hashlib, zlib
from optparse import OptionParser
from multiprocessing import Pool
try:
	import tlsh
	tlshscan = True
except Exception, e:
	tlshscan = False

tarmagic = ['POSIX tar archive (GNU)'
           , 'tar archive'
           ]

ms = magic.open(magic.MAGIC_NONE)
ms.load()

## unpack the directories to be scanned.
def unpack(directory, filename, unpackdir):
	try:
		os.stat(os.path.join(directory, filename))
	except:
		print >>sys.stderr, "Can't find %s" % filename
		return None

        filemagic = ms.file(os.path.realpath(os.path.join(directory, filename)))

        ## Assume if the files are bz2 or gzip compressed they are compressed tar files
        if 'bzip2 compressed data' in filemagic:
		if unpackdir != None:
       			tmpdir = tempfile.mkdtemp(dir=unpackdir)
		else:
       			tmpdir = tempfile.mkdtemp()
		## for some reason the tar.bz2 unpacking from python doesn't always work, like
		## aeneas-1.0.tar.bz2 from GNU, so use a subprocess instead of using the
		## Python tar functionality.
 		p = subprocess.Popen(['tar', 'jxf', os.path.join(directory, filename)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmpdir)
		(stanout, stanerr) = p.communicate()
		if p.returncode != 0:
			shutil.rmtree(tmpdir)
			return
		return tmpdir
	elif 'LZMA compressed data, streamed' in filemagic:
		if unpackdir != None:
       			tmpdir = tempfile.mkdtemp(dir=unpackdir)
		else:
       			tmpdir = tempfile.mkdtemp()
		p = subprocess.Popen(['tar', 'ixf', os.path.join(directory, filename)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmpdir)
		(stanout, stanerr) = p.communicate()
		if p.returncode != 0:
			shutil.rmtree(tmpdir)
			return
		return tmpdir
        elif 'XZ compressed data' in filemagic or ('data' in filemagic and filename.endswith('.xz')):
		if unpackdir != None:
       			tmpdir = tempfile.mkdtemp(dir=unpackdir)
		else:
       			tmpdir = tempfile.mkdtemp()
 		p = subprocess.Popen(['tar', 'Jxf', os.path.join(directory, filename)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmpdir)
		(stanout, stanerr) = p.communicate()
		if p.returncode != 0:
			shutil.rmtree(tmpdir)
			return
		return tmpdir
        elif 'gzip compressed data' in filemagic or 'compress\'d data 16 bits' in filemagic or ('Minix filesystem' in filemagic and filename.endswith('.gz')) or ('JPEG 2000 image' in filemagic and filename.endswith('.gz')):
		if unpackdir != None:
       			tmpdir = tempfile.mkdtemp(dir=unpackdir)
		else:
       			tmpdir = tempfile.mkdtemp()
 		p = subprocess.Popen(['tar', 'zxf', os.path.join(directory, filename)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmpdir)
		(stanout, stanerr) = p.communicate()
		if p.returncode != 0:
			shutil.rmtree(tmpdir)
			return
		return tmpdir
	elif 'Zip archive data' in filemagic:
		try:
			if unpackdir != None:
       				tmpdir = tempfile.mkdtemp(dir=unpackdir)
			else:
       				tmpdir = tempfile.mkdtemp()
			p = subprocess.Popen(['unzip', "-B", os.path.join(directory, filename), '-d', tmpdir], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			(stanout, stanerr) = p.communicate()
			if p.returncode != 0 and p.returncode != 1:
				print >>sys.stderr, "unpacking ZIP failed for", filename, stanerr
				shutil.rmtree(tmpdir)
				pass
			else:
				return tmpdir
		except Exception, e:
			print >>sys.stderr, "unpacking ZIP failed", e

def grabhash(filedir, filename, filehash, pool, extrahashes, temporarydir, hashcache):
	## unpack the archive. If it fails, cleanup and return.
	temporarydir = unpack(filedir, filename, temporarydir)
	if temporarydir == None:
		return None

	print "processing", filename
	sys.stdout.flush()

	## add 1 to deal with /
	lenunpackdir = len(temporarydir) + 1

	osgen = os.walk(temporarydir)

	try:
		scanfiles = []
		while True:
			i = osgen.next()
			## make sure all directories can be accessed
			for d in i[1]:
				if not os.path.islink(os.path.join(i[0], d)):
					os.chmod(os.path.join(i[0], d), stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
			for p in i[2]:
				scanfiles.append((i[0], p, extrahashes))
	except Exception, e:
		if str(e) != "":
			print >>sys.stderr, e

	## compute the hashes in parallel
	scanfile_result_sha256 = filter(lambda x: x != None, pool.map(computesha256, scanfiles, 1))
	scanfile_result = []

	cached = 0

	if len(extrahashes) != 0:
		extrahashtasks = []
		for s in scanfile_result_sha256:
			if s == None:
				continue
			(filedir, filename, sha256sum) = s
			if sha256sum in hashcache:
				tmphashes = hashcache[sha256sum]
				scanfile_result.append((filedir, filename, tmphashes))
				cached += 1
				continue
			extrahashtasks.append((filedir, filename, extrahashes, sha256sum))

		if len(extrahashtasks) != 0:
			scanfile_result_extra = filter(lambda x: x != None, pool.map(computehash, extrahashtasks, 1))
			for s in scanfile_result_extra:
				(filedir, filename, filehashes) = s
				sha256sum = filehashes['sha256']
				hashcache[sha256sum] = filehashes
				scanfile_result.append(s)
	cleanupdir(temporarydir)
	scanfile_result = map(lambda x: (x[0][lenunpackdir:],) +  x[1:], scanfile_result)
	return (scanfile_result, cached)

def cleanupdir(temporarydir):
	osgen = os.walk(temporarydir)
	try:
		while True:
			i = osgen.next()
			## make sure all directories can be accessed
			for d in i[1]:
				if not os.path.islink(os.path.join(i[0], d)):
					os.chmod(os.path.join(i[0], d), stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
			for p in i[2]:
				try:
					if not os.path.islink(os.path.join(i[0], p)):
						os.chmod(os.path.join(i[0], p), stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
				except Exception, e:
					#print e
					pass
	except StopIteration:
		pass
	try:
		shutil.rmtree(temporarydir)
	except:
		## nothing that can be done right now, so just give up
		pass

def computesha256((filedir, filename, extrahashes)):
	resolved_path = os.path.join(filedir, filename)
	if not os.path.isfile(resolved_path):
		## filter out fifo and pipe
		return None
	try:
		if not os.path.islink(resolved_path):
			os.chmod(resolved_path, stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
	except Exception, e:
		pass
	## skip links
	if os.path.islink(resolved_path):
        	return None
	scanfile = open(resolved_path, 'r')
	h = hashlib.new('sha256')
	data = scanfile.read()
	h.update(data)
	scanfile.close()
	sha256sum = h.hexdigest()
	return (filedir, filename, sha256sum)

def computehash((filedir, filename, extrahashes, sha256sum)):
	resolved_path = os.path.join(filedir, filename)
	filehashes = {}
	filehashes['sha256'] = sha256sum
	scanfile = open(resolved_path, 'r')
	data = scanfile.read()
	scanfile.close()
	for i in extrahashes:
		if i == 'crc32':
			filehashes[i] = zlib.crc32(data) & 0xffffffff
		elif i == 'tlsh':
			if os.stat(resolved_path).st_size >= 256:
				tlshhash = tlsh.hash(data)
				filehashes[i] = tlshhash
			else:
				filehashes[i] = None
		else:
			h = hashlib.new(i)
			h.update(data)
			filehashes[i] = h.hexdigest()
	filehashes['sha256'] = sha256sum
	return (filedir, filename, filehashes)

def checkalreadyscanned((filedir, filename, checksum)):
	resolved_path = os.path.join(filedir, filename)
	try:
		os.stat(resolved_path)
	except:
		print >>sys.stderr, "Can't find %s" % filename
		return None
	if checksum != None:
		filehash = checksum
	else:
		scanfile = open(resolved_path, 'r')
		h = hashlib.new('sha256')
		h.update(scanfile.read())
		scanfile.close()
		filehash = h.hexdigest()
	return (filename, filehash)

def main(argv):
	parser = OptionParser()
	parser.add_option("-f", "--filedir", action="store", dest="filedir", help="path to directory containing files to unpack", metavar="DIR")
	parser.add_option("-u", "--update", action="store_true", dest="update", help="only create manifest files for new archives")
	parser.add_option("-t", "--temporarydir", action="store", dest="unpackdir", help="set unpacking directory (default: /tmp)", metavar="DIR")

	(options, args) = parser.parse_args()
	if options.filedir == None:
		parser.error("Specify dir with files")
	else:
		try:
			filelist = open(os.path.join(options.filedir,"LIST")).readlines()
		except:
			parser.error("'LIST' not found in file dir")

	if options.unpackdir != None:
		if not os.path.exists(options.unpackdir):
			parser.error("temporary unpacking directory '%s' does not exist" % options.unpackdir)

	options.unpackdir = '/ramdisk'

	pool = Pool()

	pkgmeta = []

	checksums = {}
	if os.path.exists(os.path.join(options.filedir, "SHA256SUM")):
		checksumlines = open(os.path.join(options.filedir, "SHA256SUM")).readlines()
		for c in checksumlines[1:]:
			checksumsplit = c.strip().split()
			if len(checksumsplit) < 2:
				continue
			archivefilename = checksumsplit[0]
			archivechecksum = checksumsplit[1]
			checksums[archivefilename] = archivechecksum

	extrahashes = ['md5', 'sha1', 'crc32']
	if tlshscan:
		extrahashes.append('tlsh')

	for unpackfile in filelist:
		try:
			unpacks = unpackfile.strip().split()
			if len(unpacks) == 4:
				(package, version, filename, origin) = unpacks
				batarchive = False
			else:
				(package, version, filename, origin, bat) = unpacks
				if bat == 'batarchive':
					batarchive = True
				else:
					batarchive = False
			pkgmeta.append((options.filedir, filename, checksums[filename]))
		except Exception, e:
			# oops, something went wrong
			print >>sys.stderr, e, unpackfile
	res = filter(lambda x: x != None, pool.map(checkalreadyscanned, pkgmeta, 1))

	processed_hashes = set()
	manifestdir = os.path.join(options.filedir, "MANIFESTS")
	if os.path.exists(manifestdir) and os.path.isdir(manifestdir):
		outputdir = manifestdir
	else:
		outputdir = "/tmp"

	print "outputting hashes to %s" % outputdir
	sys.stdout.flush()

	uniquehashes = set()
	hashcache = {}
	manifestfiles = set()
	for r in res:
		(filename, filehash) = r
		if filehash in uniquehashes:
			continue
		uniquehashes.add(filehash)
		if options.update and os.path.exists(os.path.join(outputdir, "%s.bz2" % filehash)):
			continue
		grabres = grabhash(options.filedir, filename, filehash, pool, extrahashes, options.unpackdir, hashcache)
		if grabres == None:
			continue
		(unpackres, cached) = grabres
		if cached == 0:
			hashcache = {}
		## first write the scanned/supported hashes, in the order in which they
		## appear for each file
		manifest = os.path.join(outputdir, "%s" % filehash)
		manifestfile = open(manifest, 'w')
		if extrahashes == []:
			manifestfile.write("sha256\n")
		else:
			hashesstring = "sha256"
			for h in extrahashes:
				hashesstring += "\t%s" % h
			manifestfile.write("%s\n" % hashesstring)
		for u in unpackres:
			if extrahashes == []:
				manifestfile.write("%s\t%s\n" % (os.path.join(u[0], u[1]), u[2]['sha256']))
			else:
				hashesstring = "%s" % u[2]['sha256']
				for h in extrahashes:
					hashesstring += "\t%s" % u[2][h]
				manifestfile.write("%s\t%s\n" % (os.path.join(u[0], u[1]), hashesstring))
		manifestfile.close()
		manifestfiles.add((outputdir, filehash))
	pool.map(compressfiles, manifestfiles)
	pool.terminate()
	print "%d hashes were written to %s" % (len(uniquehashes), outputdir)
	sys.stdout.flush()

def compressfiles((outputdir, filehash)):
	fin = open(os.path.join(outputdir, filehash), 'rb')
	fout = bz2.BZ2File(os.path.join(outputdir, "%s.bz2" % filehash), 'wb')
	fout.write(fin.read())
	fout.close()
	fin.close()
	os.unlink(fin.name)

if __name__ == "__main__":
    main(sys.argv)
