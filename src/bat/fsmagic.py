#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2009-2016 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''This file contains information about how to recognize certain
files, file systems, compression, and so on automatically and which
methods or functions to invoke to unpack these files for further
analysis.'''

## information from:
## 1. /usr/share/magic
## 2. include/linux/magic.h in the Linux kernel sources
## 3. http://www.squashfs-lzma.org/
## 4. http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=364260
## 5. various other places

## This is not the same as the magic database, but just a list of
## identifiers that are used for these file systems, compressed files,etc.
## In BAT a lot more work is done to verify what a file really is, which
## the magic database does not do.

fsmagic = {
            'gzip':             '\x1f\x8b\x08',     # x08 is the only compression method according to RFC 1952
            'compress':         '\x1f\x9d',
            'bz2':              'BZh',
            'rar':              'Rar!\x1a\x07',
            'rarfooter':        '\xc4\x3d\x7b\x00\x40\x07\x00', # http://forensicswiki.org/wiki/RAR#Terminator_.28terminator.29
            'zip':              '\x50\x4b\x03\04',
            'zipend':           '\x50\x4b\x05\06',
            'lrzip':            'LRZI',
            'rzip':             'RZIP',
            'squashfs1':        '\x68\x73\x71\x73', # hsqs -- little endian
            'squashfs2':        '\x73\x71\x73\x68', # sqsh -- big endian
            'squashfs3':        '\x71\x73\x68\x73', # qshs -- little endian
            'squashfs4':        '\x73\x68\x73\x71', # shsq -- big endian
            'squashfs5':        '\x74\x71\x73\x68', # tqsh - used in DD-WRT
            'squashfs6':        '\x68\x73\x71\x74', # hsqt - used in DD-WRT
            'squashfs7':        '\x73\x71\x6c\x7a', # sqlz
            'android-sparse':   '\x3a\xff\x26\xed',
            'lzma_alone':       '\x5d\x00\x00',
            'lzma_alone_alt':   '\x6d\x00\x00',     # used in OpenWrt
            'lzma_alone_alt2':  '\x6c\x00\x00',     # seen in some routers, like ZyXEL NBG5615
            '7z':               '7z\xbc\xaf\x27\x1c',
            'xz':               '\xfd\x37\x7a\x58\x5a\x00',
            'xztrailer':        '\x59\x5a',
            'lzip':             'LZIP',
            'lzop':              '\x89\x4c\x5a\x4f\x00\x0d\x0a\x1a\x0a',
            'lha':              '-lh7-',
            'cramfs_le':        '\x45\x3d\xcd\x28',
            'cramfs_be':        '\x28\xcd\x3d\x45',
            'romfs':            '-rom1fs-',
            'jffs2_le':         '\x85\x19',
            'jffs2_be':         '\x19\x85',
            'ubifs':            '\x31\x18\x10\x06',
            'ubi':              '\x55\x42\x49\x23',
            'rpm':              '\xed\xab\xee\xdb',
            'ext2':             '\x53\xef',        # little endian
            'minix':            '\x8f\x13',        # specific version of Minix v1 file system
            'arj':              '\x60\xea',
            'cab':              'MSCF\x00\x00\x00\x00',    # first four bytes following header are always 0
            'installshield':    'ISc(',
            'pkbac':            'PKBAC',
            'winrar':           'WinRAR',
            'png':              '\x89PNG\x0d\x0a\x1a\x0a',
            'pngtrailer':       '\x00\x00\x00\x00IEND\xae\x42\x60\x82', # length, chunk type and CRC for PNG trailer are always the same
            'cpiotrailer':      'TRAILER!!!',
            'bmp':              'BM',
            'jpeg':             '\xff\xd8',
            'jpegtrailer':      '\xff\xd9',
            'jfif':             'JFIF',
            'gif87':            'GIF87a',
            'gif89':            'GIF89a',
            'ico':              '\x00\x00\x01\x00',
            'riff':             'RIFF',
            'cpio1':            '070701',
            'cpio2':            '070702',
            'cpio3':            '070707',
            'iso9660':          'CD001',
            'swf':              'CWS',
            'pdf':              '%PDF-',
            'pdftrailer':       '%%EOF',
            'ar':               '!<arch>',
            'tar1':             'ustar\x00',
            'tar2':             'ustar\x20',
            'java_serialized':  '\xac\xed\x00',
            'fat12':  		'FAT12',
            'fat16':  		'FAT16',
            'pe':  		'MZ',
            'upx':  		'UPX',
            'java': 		'\xca\xfe\xba\xbe',
            'pack200':		'\xca\xfe\xd0\x0d',
            'dex':		'dex\n', ## Android Dex
            'odex':		'dey\n', ## Android Odex
            'oat':		'oat\n', ## Android OAT
            'otf':		'OTTO',
            'ttf':		'\x00\x01\x00\x00',
            'id3':		'TAG',
            'id3v2':		'ID3',
            'mp4':		'ftyp',
            'ogg':  		'OggS',
            'sqlite3':		'SQLite format 3\x00',
            'u-boot':		'\x27\x05\x19\x56',
            'yaffs2':		'\x03\x00\x00\x00\x01\x00\x00\x00\xff\xff', ## this is not a an official signature, just occuring frequently
            'plf':		'\x50\x4c\x46\x21',
            'chm':		'ITSF\x03\x00\x00\x00\x60\x00\x00\x00\x01\x00\x00\x00',
            'msi':		'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', ## not sure this is a correct signature
            'windowsassemblyheader':		'<assembly',
            'windowsassemblytrailer':		'</assembly>',
            'appledouble':	'\x00\x05\x16\x07',
            'mswim':	        'MSWIM\x00\x00\x00',
            'certificate':	'-----BEGIN',
            'androidbackup':	'ANDROID BACKUP\n',
            'aiff':		'FORM',
            'woff':		'wOFF',
            'woff2':		'wOF2',
            'xar':		'\x78\x61\x72\x21',
            'ics':		'acsp',
            'elf':		'\x7f\x45\x4c\x46',
            'bflt':		'\x62\x46\x4c\x54',
          }

## some offsets can be found after a certain number of bytes, but
## the actual file system or file starts earlier
correction = {
               'ext2':    0x438,
               'minix':   0x410,
               'iso9660': 32769,
               'tar1':    0x101,
               'tar2':    0x101,
               'fat12':   54,
               'fat16':   54,
               'lha':     2,
               'ics':     36,
             }

## collection of markers that should be scanned together
squashtypes = ['squashfs1', 'squashfs2', 'squashfs3', 'squashfs4', 'squashfs5', 'squashfs6']
lzmatypes   = ['lzma_alone', 'lzma_alone_alt', 'lzma_alone_alt2']
cpio        = ['cpio1', 'cpio2', 'cpio3']
gif         = ['gif87', 'gif89']
tar         = ['tar1', 'tar2']
