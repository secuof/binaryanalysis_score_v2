#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2009-2013 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
This script can be used to initialize an empty knowledgebase and create all tables.
'''

import os, sys, sqlite3
from optparse import OptionParser

def main(argv):
        parser = OptionParser()
	parser.add_option("-d", "--database", dest="db", help="path to database", metavar="FILE")
	(options, args) = parser.parse_args()
	if options.db == None:
                parser.error("Path to database file needed")
        try:
                conn = sqlite3.connect(options.db)
        except:
                print "Can't open database file"
                sys.exit(1)

	c = conn.cursor()

	## create some tables
	c.execute('''create table if not exists chipset (name text, vendor text, family text)''')
	c.execute('''create table if not exists device (id integer primary key autoincrement, vendor text, name text, version text, chipset text, upstream text)''')
	c.execute('''create table if not exists binary (id integer primary key autoincrement, sha256 text, deviceid integer)''')
	c.execute('''create index if not exists sha256_index on binary (sha256)''')

	conn.commit()
	c.close()

if __name__ == "__main__":
        main(sys.argv)
