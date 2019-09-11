#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2014-2015 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

import sys, os, os.path
import sqlite3
from optparse import OptionParser

def main(argv):
	alpha = 5.0

	parser = OptionParser()
	parser.add_option("-d", "--database", action="store", dest="db", help="path to caching database", metavar="FILE")
	(options, args) = parser.parse_args()
	if options.db == None:
		parser.error("Path to caching database")
	if not os.path.exists(options.db):
		print >>sys.stderr, "Caching database %s does not exist" % options.db
		sys.exit(1)

	conn = sqlite3.connect(options.db)
	c = conn.cursor()

	c.execute("create table if not exists scores (stringidentifier text, packages int, score real)")
	c.execute("create index if not exists scoresindex on scores(stringidentifier)")
	conn.commit()
	c2 = conn.cursor()

	c.execute("select distinct stringidentifier from stringscache")
	programstrings = c.fetchmany(10000)
	while programstrings != []:
		for p in programstrings:
			pkgs = {}
			filenames = {}

			pfs = c2.execute("select package, filename from stringscache where stringidentifier=?", p).fetchall()
			packages = set(map(lambda x: x[0], pfs))

			if len(packages) == 1:
				score = float(len(p[0]))
			else:
				for pf in pfs:
					(package, filename) = pf
					if not filenames.has_key(filename):
						filenames[filename] = [package]
					else:   
						filenames[filename] = list(set(filenames[filename] + [package]))
				try:
					score = float(len(p[0])) / pow(alpha, (len(filenames) - 1))
				except Exception, e:
					score = len(p[0]) / sys.maxint
				## cut off for for example postgresql
				if score < 1e-37:
					score = 0.0
			c2.execute("insert into scores(stringidentifier, packages, score) values (?,?,?)", (p[0], len(packages), float(score)))
		programstrings = c.fetchmany(10000)
	conn.commit()
	c2.close()
	print "vacuuming"
	c.execute("vacuum")
	conn.commit()
	c.close()
	conn.close()
	
if __name__ == "__main__":
	main(sys.argv)
