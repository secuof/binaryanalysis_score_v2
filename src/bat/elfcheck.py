#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2012-2016 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
This module contains methods to verify ELF files and help extract data
from ELF files such as the architecture, sections, symbols, and so on.

Note: some vendors run sstrip on the binaries. There are versions of the
sstrip tool that are buggy and create files with a section header that is
actually incorrect and will for example confuse readelf:

https://dev.openwrt.org/ticket/6847
https://bugs.busybox.net/show_bug.cgi?id=729
'''

import sys, os, subprocess, os.path, struct, math
import tempfile, re

## information about ELF was collected from the following places:
##
## https://en.wikipedia.org/wiki/Executable_and_Linkable_Format
## https://docs.oracle.com/cd/E19683-01/816-1386/chapter6-43405/index.html
## https://refspecs.linuxbase.org/elf/elf.pdf
## https://android.googlesource.com/platform/art/+/master/runtime/elf.h
##
## mappings of architectures to names
architecturemapping = { 0: None
                     , 1: "AT&T WE 32100"
                     , 2: "SPARC"
                     , 3: "Intel 80386"
                     , 4: "Motorola 68000"
                     , 5: "Motorola 88000"
                     , 6: "Intel 80486"
                     , 7: "Intel 80860"
                     , 8: "MIPS R3000"
                     , 9: "IBM System/370"
                     , 10: "MIPS RS3000 Little-endian"
                     , 15: "Hewlett-Packard PA-RISC"
                     , 17: "Fujitsu VPP500"
                     , 18: "SPARC32+" # // Enhanced instruction set SPARC
                     , 19: "Intel 80960"
                     , 20: "PowerPC"
                     , 21: "PowerPC64"
                     , 22: "IBM System/390"
                     , 23: "IBM SPU/SPC"
                     , 36: "NEC V800"
                     , 37: "Fujitsu FR20"
                     , 38: "TRW RH-32"
                     , 39: "Motorola RCE"
                     , 40: "ARM"
                     , 41: "DEC Alpha"
                     , 42: "Hitachi SH"
                     , 43: "SPARC V9"
                     , 44: "Siemens TriCore"
                     , 45: "Argonaut RISC Core"
                     , 46: "Hitachi H8/300"
                     , 47: "Hitachi H8/300H"
                     , 48: "Hitachi H8S"
                     , 49: "Hitachi H8/500"
                     , 50: "Intel IA-64"
                     , 51: "Stanford MIPS-X"
                     , 52: "Motorola ColdFire"
                     , 53: "Motorola M68HC12"
                     , 54: "Fujitsu MMA Multimedia Accelerator"
                     , 55: "Siemens PCP"
                     , 56: "Sony nCPU embedded RISC processor"
                     , 57: "Denso NDR1 microprocessor"
                     , 58: "Motorola Star*Core processor"
                     , 59: "Toyota ME16 processor"
                     , 60: "STMicroelectronics ST100 processor"
                     , 61: "Advanced Logic Corp. TinyJ"
                     , 62: "AMD X86-64"
                     , 63: "Sony DSP Processor"
                     , 64: "Digital Equipment Corp. PDP-10"
                     , 65: "Digital Equipment Corp. PDP-11"
                     , 66: "Siemens FX66 microcontroller"
                     , 67: "STMicroelectronics ST9+ 8/16 bit microcontroller"
                     , 68: "STMicroelectronics ST7 8-bit microcontroller"
                     , 69: "Motorola MC68HC16 Microcontroller"
                     , 70: "Motorola MC68HC11 Microcontroller"
                     , 71: "Motorola MC68HC08 Microcontroller"
                     , 72: "Motorola MC68HC05 Microcontroller"
                     , 73: "Silicon Graphics SVx"
                     , 74: "STMicroelectronics ST19 8-bit microcontroller"
                     , 75: "Digital VAX"
                     , 76: "ETRAX CRIS"
                     , 77: "Javelin"
                     , 78: "Element 14 64-bit DSP Processor"
                     , 79: "ZSP LSI Logic 16-bit DSP Processor"
                     , 80: "MMIX (Donald Knuth's educational 64-bit processor)"
                     , 81: "Harvard University machine-independent object files"
                     , 82: "SiTera Prism"
                     , 83: "Atmel AVR 8-bit microcontroller"
                     , 84: "Fujitsu FR30"
                     , 85: "Mitsubishi D10V"
                     , 86: "Mitsubishi D30V"
                     , 87: "NEC v850"
                     , 88: "Mitsubishi M32R"
                     , 89: "Matsushita MN10300"
                     , 90: "Matsushita MN10200"
                     , 91: "picoJava"
                     , 92: "OpenRISC 32-bit embedded processor"
                     , 93: "ARC International ARCompact processor"
                     , 94: "Tensilica Xtensa Architecture"
                     , 95: "Alphamosaic VideoCore processor"
                     , 96: "Thompson Multimedia General Purpose Processor"
                     , 97: "National Semiconductor 32000 series"
                     , 98: "Tenor Network TPC processor"
                     , 99: "Trebia SNP 1000 processor"
                     , 100: "STMicroelectronics ST200"
                     , 101: "Ubicom IP2xxx"
                     , 102: "MAX Processor"
                     , 103: "National Semiconductor CompactRISC microprocessor"
                     , 104: "Fujitsu F2MC16"
                     , 105: "Texas Instruments embedded microcontroller msp430"
                     , 106: "Analog Devices Blackfin (DSP) processor"
                     , 107: "S1C33 Family of Seiko Epson processors"
                     , 108: "Sharp embedded microprocessor"
                     , 109: "Arca RISC Microprocessor"
                     , 110: "MPRC UniCore"
                     , 111: "eXcess: 16/32/64-bit configurable embedded CPU"
                     , 112: "Icera Semiconductor Inc. Deep Execution Processor"
                     , 113: "Altera Nios II soft-core processor"
                     , 114: "National Semiconductor CompactRISC CRX"
                     , 115: "Motorola XGATE embedded processor"
                     , 116: "Infineon C16x/XC16x processor"
                     , 117: "Renesas M16C series microprocessors"
                     , 118: "Microchip Technology dsPIC30F Digital Signal Controller"
                     , 119: "Freescale Communication Engine RISC core"
                     , 120: "Renesas M32C series microprocessors"
                     , 131: "Altium TSK3000 core"
                     , 132: "Freescale RS08 embedded processor"
                     , 133: "Analog Devices SHARC"
                     , 134: "Cyan Technology eCOG2 microprocessor"
                     , 135: "Sunplus S+core7 RISC processor"
                     , 136: "New Japan Radio (NJR) 24-bit DSP Processor"
                     , 137: "Broadcom VideoCore III processor"
                     , 138: "RISC processor for Lattice FPGA architecture"
                     , 139: "Seiko Epson C17"
                     , 140: "Texas Instruments TMS320C6000"
                     , 141: "Texas Instruments TMS320C2000"
                     , 142: "Texas Instruments TMS320C55x"
                     , 160: "STMicroelectronics 64bit VLIW Data Signal Processor"
                     , 161: "Cypress M8C microprocessor"
                     , 162: "Renesas R32C series microprocessors"
                     , 163: "NXP Semiconductors TriMedia"
                     , 164: "Qualcomm Hexagon processor"
                     , 165: "Intel 8051"
                     , 166: "STMicroelectronics STxP7x RISC processor"
                     , 167: "Andes Technology compact code size embedded RISC"
                     , 168: "Cyan Technology eCOG1X"
                     , 169: "Dallas Semiconductor MAXQ30 Core Micro-controllers"
                     , 170: "New Japan Radio (NJR) 16-bit DSP Processor"
                     , 171: "M2000 Reconfigurable RISC Microprocessor"
                     , 172: "Cray Inc. NV2 vector architecture"
                     , 173: "Renesas RX"
                     , 174: "Imagination Technologies META"
                     , 175: "MCST Elbrus"
                     , 176: "Cyan Technology eCOG16"
                     , 177: "National Semiconductor CompactRISC CR16"
                     , 178: "Freescale Extended Time Processing Unit"
                     , 179: "Infineon Technologies SLE9X core"
                     , 180: "Intel L10M"
                     , 181: "Intel K10M"
                     , 183: "ARM AArch64"
                     , 185: "Atmel Corporation AVR32"
                     , 186: "STMicroeletronics STM8"
                     , 187: "Tilera TILE64"
                     , 188: "Tilera TILEPro"
                     , 190: "NVIDIA CUDA architecture"
                     , 191: "Tilera TILE-Gx"
                     , 192: "CloudShield"
                     , 193: "KIPO-KAIST Core-A 1st generation"
                     , 194: "KIPO-KAIST Core-A 2nd generation"
                     , 195: "Synopsys ARCompact V2"
                     , 196: "Open8 8-bit RISC soft processor core"
                     , 197: "Renesas RL78"
                     , 198: "Broadcom VideoCore V processor"
                     , 199: "Renesas 78KOR"
                     , 200: "Freescale 56800EX"
                     }

## read the architecture of a (validated) ELF file
def getArchitecture(filename, tags):
	## return if the file is not a valid ELF file
	if not 'elf' in tags:
		return
	elffile = open(filename, 'rb')

	## first read the ELF header
	elffile.seek(0)
	elfbytes = elffile.read(64)

	## then check if this is a little endian or big endian binary
	littleendian = True
	if struct.unpack('>B', elfbytes[5])[0] != 1:
		littleendian = False

	## extract the machine type from the right place in the binary
	if littleendian:
		elfmachinebyte = struct.unpack('<H', elfbytes[0x12:0x12+2])[0]
	else:
		elfmachinebyte = struct.unpack('>H', elfbytes[0x12:0x12+2])[0]

	## then look up the machine type in the list of architectures
	if elfmachinebyte in architecturemapping:
		architecture = architecturemapping[elfmachinebyte]
	else:
		architecture = "UNKNOWN"
	elffile.close()
	return architecture

## extract information about a section given a section name
def getSection(filename, sectionname, debug=False):
	(totalelf, elfresult) = parseELF(filename, 0, debug)
	returnsection = None
	if elfresult == None:
		return
	for i in elfresult['sections']:
		if elfresult['sections'][i]['name'] == sectionname:
			returnsection = i
			break
	if returnsection != None:
		return elfresult['sections'][returnsection]

## get all the symbols from an ELF binary.
## This is similar to "readelf -s"
## For most binaries (stripped) this is equivalent to
## getting the dynamic symbol table.
## In case the file has not been stripped this also
## includes the debugging symbols.
def getAllSymbols(filename, debug=False):
	(totalelf, elfresult) = parseELF(filename, 0, debug)
	symres = []
	symbolres = getSymbols(filename, elfresult, debug)
	if symbolres != None:
		symres += symbolres
	symbolres = getDynamicSymbols(filename, elfresult, debug)
	if symbolres != None:
		symres += symbolres
	return symres

## similar to readelf -s but only regular symbols (not dynamic)
## This will only return results on binaries that are not stripped
def getSymbols(filename, elfresult=None, debug=False):
	return getSymbolsAbstraction(filename, 'symbol', elfresult, debug)

## similar to readelf --dyn-syms (just the dynamic section)
def getDynamicSymbols(filename, elfresult=None, debug=False):
	return getSymbolsAbstraction(filename, 'dynamic', elfresult, debug)

## A generic method to get symbols from either the dynamic symbol
## table or the symbol table (non-stripped binaries)
def getSymbolsAbstraction(filename, symboltype, elfresult, debug=False):
	if elfresult == None:
		(totalelf, elfresult) = parseELF(filename, 0, debug)
		if not totalelf:
			return

	symsection = None
	strsection = None
	for i in elfresult['sections']:
		if symboltype == 'dynamic':
			if elfresult['sections'][i]['sectiontype'] == 11:
				symsection = i
		elif symboltype == 'symbol':
			if elfresult['sections'][i]['sectiontype'] == 2:
				symsection = i
		if symboltype == 'dynamic':
			if elfresult['sections'][i]['name'] == '.dynstr':
				if elfresult['sections'][i]['sectiontype'] == 3:
					strsection = i
		else:
			if elfresult['sections'][i]['name'] == '.strtab':
				if elfresult['sections'][i]['sectiontype'] == 3:
					strsection = i

	## no need to continue if both the symsection
	## and strsection are None (most likely indicating a corrupt ELF file)
	if symsection == None:
		return

	if strsection == None:
		return

	bit32 = elfresult['bit32']
	littleendian = elfresult['littleendian']

	## first, get the dynamic symbol section
	elffile = open(filename, 'rb')
	elffile.seek(elfresult['sections'][symsection]['sectionoffset'])
	elfbytes = elffile.read(elfresult['sections'][symsection]['sectionsize'])

	## then get the string section from the binary
	elffile.seek(elfresult['sections'][strsection]['sectionoffset'])
	strbytes = elffile.read(elfresult['sections'][strsection]['sectionsize'])
	elffile.close()

	dynamicsymbols = []

	## Then process all the symbol entries.
	## Various pieces of information are extracted, such as type,
	## binding and visibility. The name of the symbol is extracted
	## from the string section using an offset defined in the symbol
	## entry.
	if bit32:
		## for 32 bit binaries each entry takes up 16 bytes
		entrysize = 16
	else:
		## for 64 bit binaries each entry takes up 24 bytes
		entrysize = 24
	for i in xrange(0, len(elfbytes)/entrysize):
		dynsymres = {}
		dynsymres['index'] = i
		if bit32:
			if littleendian:
				st_name = struct.unpack('<I', elfbytes[i*entrysize:i*entrysize+4])[0]
				st_value = struct.unpack('<I', elfbytes[i*entrysize+4:i*entrysize+8])[0]
				st_size = struct.unpack('<I', elfbytes[i*entrysize+8:i*entrysize+12])[0]
				st_info = ord(elfbytes[i*entrysize+12])
				st_other = ord(elfbytes[i*entrysize+13])
				st_shndx = struct.unpack('<H', elfbytes[i*entrysize+14:i*entrysize+16])[0]
			else:
				st_name = struct.unpack('>I', elfbytes[i*entrysize:i*entrysize+4])[0]
				st_value = struct.unpack('>I', elfbytes[i*entrysize+4:i*entrysize+8])[0]
				st_size = struct.unpack('>I', elfbytes[i*entrysize+8:i*entrysize+12])[0]
				st_info = ord(elfbytes[i*entrysize+12])
				st_other = ord(elfbytes[i*entrysize+13])
				st_shndx = struct.unpack('>H', elfbytes[i*entrysize+14:i*entrysize+16])[0]
		else:
			if littleendian:
				st_name = struct.unpack('<I', elfbytes[i*entrysize:i*entrysize+4])[0]
				st_info = ord(elfbytes[i*entrysize+4])
				st_other = ord(elfbytes[i*entrysize+5])
				st_shndx = struct.unpack('<H', elfbytes[i*entrysize+6:i*entrysize+8])[0]
				st_value = struct.unpack('<Q', elfbytes[i*entrysize+8:i*entrysize+16])[0]
				st_size = struct.unpack('<Q', elfbytes[i*entrysize+16:i*entrysize+24])[0]
			else:
				st_name = struct.unpack('>I', elfbytes[i*entrysize:i*entrysize+4])[0]
				st_info = ord(elfbytes[i*entrysize+4])
				st_other = ord(elfbytes[i*entrysize+5])
				st_shndx = struct.unpack('>H', elfbytes[i*entrysize+6:i*entrysize+8])[0]
				st_value = struct.unpack('>Q', elfbytes[i*entrysize+8:i*entrysize+16])[0]
				st_size = struct.unpack('>Q', elfbytes[i*entrysize+16:i*entrysize+24])[0]

		endofname = strbytes.find('\x00', st_name)
		dynsymres['name'] = strbytes[st_name:endofname]
		dynsymres['section'] = st_shndx
		dynsymres['size'] = st_size
		dynsymres['value'] = st_value
		binding = st_info >> 4
		if binding == 0:
			dynsymres['binding'] = 'local'
		elif binding == 1:
			dynsymres['binding'] = 'global'
		elif binding == 2:
			dynsymres['binding'] = 'weak'
		elif binding == 10:
			dynsymres['binding'] = 'unique' # STB_LOOS according to ELF specs, so might be Linux specific
		else:
			## by default ignore, TODO
			dynsymres['binding'] = 'ignore'

		## extract the symbol type
		dyntype = st_info%16
		if dyntype == 0:
			dynsymres['type'] = 'notype'
		elif dyntype == 1:
			## symbol is an object (variable)
			dynsymres['type'] = 'object'
		elif dyntype == 2:
			## symbol is a function
			dynsymres['type'] = 'func'
		elif dyntype == 3:
			## symbol is a section
			dynsymres['type'] = 'section'
		elif dyntype == 4:
			## symbol is a file name
			dynsymres['type'] = 'file'
		elif dyntype == 6:
			dynsymres['type'] = 'tls' # thread local storage
		elif dyntype == 10:
			## symbol is an ifunc (GNU extension)
			dynsymres['type'] = 'ifunc' # STT_LOOS according to ELF specs, so might be Linux specific
		else:
			## by default ignore, TODO
			dynsymres['type'] = 'ignore'

		## extract the visibility
		if st_other & 0x03 == 0:
			dynsymres['visibility'] = 'default'
		elif st_other & 0x03 == 1:
			dynsymres['visibility'] = 'internal'
		elif st_other & 0x03 == 2:
			dynsymres['visibility'] = 'hidden'
		elif st_other & 0x03 == 3:
			dynsymres['visibility'] = 'protected'
		dynsymres['symboltype'] = symboltype
		dynamicsymbols.append(dynsymres)
	return dynamicsymbols

## similar to readelf -d
def getDynamicLibs(filename, debug=False):
	(totalelf, elfresult) = parseELF(filename, 0, debug)
	if not totalelf:
		return

	if not 'dynamic' in elfresult:
		return
	
	dynamicsection = None
	dynstrsection = None
	for i in elfresult['sections']:
		if elfresult['sections'][i]['name'] == '.dynstr':
			dynstrsection = i
		if elfresult['sections'][i]['name'] == '.dynamic':
			dynamicsection = i

	if dynamicsection == None:
		return

	if elfresult['sections'][dynamicsection]['sectiontype'] != 6:
		return

	if elfresult['sections'][dynstrsection]['sectiontype'] != 3:
		return

	bit32 = elfresult['bit32']
	littleendian = elfresult['littleendian']

	## first, get the dynamic section
	elffile = open(filename, 'rb')
	elffile.seek(elfresult['sections'][dynamicsection]['sectionoffset'])
	elfbytes = elffile.read(elfresult['sections'][dynamicsection]['sectionsize'])

	elffile.seek(elfresult['sections'][dynstrsection]['sectionoffset'])
	dynstrbytes = elffile.read(elfresult['sections'][dynstrsection]['sectionsize'])
	elffile.close()

	## then process the entries
	if bit32:
		tagsize = 4
	else:
		tagsize = 8

	needed_names = []
	sonames = []
	rpathname = None
	for i in xrange(0, len(elfbytes)/tagsize, 2):
		tagbytes = elfbytes[i*tagsize:i*tagsize+tagsize]
		if littleendian:
			if bit32:
				d_tag = struct.unpack('<I', tagbytes)[0]
			else:
				d_tag = struct.unpack('<Q', tagbytes)[0]
		else:
			if bit32:
				d_tag = struct.unpack('>I', tagbytes)[0]
			else:
				d_tag = struct.unpack('>Q', tagbytes)[0]

		if d_tag == 1:
			## equivalent to NEEDED in readelf output
			offsetbytes = elfbytes[i*tagsize+tagsize:i*tagsize+tagsize*2]
			if littleendian:
				if bit32:
					d_needed_offset = struct.unpack('<I', offsetbytes)[0]
				else:
					d_needed_offset = struct.unpack('<Q', offsetbytes)[0]
			else:
				if bit32:
					d_needed_offset = struct.unpack('>I', offsetbytes)[0]
				else:
					d_needed_offset = struct.unpack('>Q', offsetbytes)[0]
			endofneededname = dynstrbytes.find('\x00', d_needed_offset)
			needed_names.append(dynstrbytes[d_needed_offset:endofneededname])
		elif d_tag == 14:
			## equivalent to SONAME in readelf output
			offsetbytes = elfbytes[i*tagsize+tagsize:i*tagsize+tagsize*2]
			if littleendian:
				if bit32:
					soname_offset = struct.unpack('<I', offsetbytes)[0]
				else:
					soname_offset = struct.unpack('<Q', offsetbytes)[0]
			else:
				if bit32:
					soname_offset = struct.unpack('>I', offsetbytes)[0]
				else:
					soname_offset = struct.unpack('>Q', offsetbytes)[0]
			endofsoname = dynstrbytes.find('\x00', soname_offset)
			soname = dynstrbytes[soname_offset:endofsoname]
			sonames.append(soname)
		elif d_tag == 15:
			## equivalent to RPATH in readelf output
			offsetbytes = elfbytes[i*tagsize+tagsize:i*tagsize+tagsize*2]
			if littleendian:
				if bit32:
					rpath_offset = struct.unpack('<I', offsetbytes)[0]
				else:
					rpath_offset = struct.unpack('<Q', offsetbytes)[0]
			else:
				if bit32:
					rpath_offset = struct.unpack('>I', offsetbytes)[0]
				else:
					rpath_offset = struct.unpack('>Q', offsetbytes)[0]
			endofrpathname = dynstrbytes.find('\x00', rpath_offset)
			rpathname = dynstrbytes[rpath_offset:endofrpathname]

	dynamic_res = {}

	if rpathname != None:
		dynamic_res['rpathname'] = rpathname
	if sonames != []:
		dynamic_res['sonames'] = sonames
	if needed_names != []:
		dynamic_res['needed_libs'] = needed_names
	return dynamic_res

## method to verify if a file is a valid ELF file
##
## Use several specifications:
## http://en.wikipedia.org/wiki/Executable_and_Linkable_Format
## https://refspecs.linuxbase.org/elf/elf.pdf
## https://www.uclibc.org/docs/elf-64-gen.pdf (important for 64 bit offsets)
##
## For these checks the ELF header, the program header and the section
## headers are looked at.
##
def verifyELF(filename, tempdir=None, tags=[], offsets={}, scanenv={}, debug=False, unpacktempdir=None):
	offset = 0
	if not 'binary' in tags:
		return []
	if 'compressed' in tags or 'graphics' in tags or 'xml' in tags:
		return []
	elffile = open(filename, 'rb')
	elffile.seek(offset)
	elfbytes = elffile.read(4)
	if elfbytes != '\x7f\x45\x4c\x46':
		elffile.close()
		return []

	newtags = []
	filesize = os.stat(filename).st_size

	(totalelf, elfresult) = parseELF(filename, 0, debug)

	if not totalelf:
		return []

	if not elfresult['dynamic']:
		newtags.append("static")
	else:
		newtags.append("dynamic")

	newtags.append(elfresult['elftype'])

	if "__ksymtab_strings" in elfresult['sectionnames']:
		## some Linux kernel specific data is stored in a
		## separate section, so it is easy to recognize
		newtags.append('linuxkernel')
	elif "oat_patches" in elfresult['sectionnames'] or '.text.oat_patches' in elfresult['sectionnames']:
		## newer Android programs are actually ELF files, with
		## the dex opcodes stored in the .rodata section
		newtags.append('oat')
		newtags.append('android')
	newtags.append('elf')
	return newtags

## method to parse an ELF file
## returns the following data:
## * endianness
## * 32 bit or 64 bit
## * ELF type
## * architecture
## * section names
## * section meta data
## * is ELF file dynamically linked (or could be)?
##
## First the ELF header is checked, then the program header
## table, then the section header table
##
## For thorough documentation of each of the parts consult
## the ELF documentation referred above.
def parseELF(filename, offset=0, debug=False):
	elffile = open(filename, 'rb')

	elfresult = {}
	filesize = os.stat(filename).st_size

	## read 64 bytes for the header
	elffile.seek(offset)
	elfbytes = elffile.read(64)
	if len(elfbytes) != 64:
		elffile.close()
		return (False, None)

	if elfbytes[0:4] != '\x7f\x45\x4c\x46':
		elffile.close()
		return (False, None)

	iself = False

	## just set some default values: little endian, 32 bit
	littleendian = True
	bit32 = True

	## first check if this is a 32 bit or 64 bit binary
	if struct.unpack('>B', elfbytes[4])[0] != 1:
		bit32 = False
	## then check if this is a little endian or big endian binary
	if struct.unpack('>B', elfbytes[5])[0] != 1:
		littleendian = False

	elfresult['bit32'] = bit32
	elfresult['littleendian'] = littleendian

	## first determine the size of the ELF header
	if bit32:
		elfunpackbytes = elfbytes[0x28:0x28+2]
	else:
		elfunpackbytes = elfbytes[0x34:0x34+2]
	if littleendian:
		elfheadersize = struct.unpack('<H', elfunpackbytes)[0]
	else:
		elfheadersize = struct.unpack('>H', elfunpackbytes)[0]

	if not (elfheadersize == 52 or elfheadersize == 64):
		elffile.close()
		return (False, None)

	## ELF header cannot extend past the end of the file
	if offset + elfheadersize > filesize:
		elffile.close()
		return (False, None)

	if elfheadersize == 0:
		elffile.close()
		return (False, None)

	## then read the actual ELF header
	elffile.seek(offset)
	elfbytes = elffile.read(elfheadersize)

	## check the ELF type.
	if littleendian:
		elftypebyte = struct.unpack('<H', elfbytes[0x10:0x10+2])[0]
	else:
		elftypebyte = struct.unpack('>H', elfbytes[0x10:0x10+2])[0]
	if elftypebyte == 0:
		elftype = 'elftypenone'
	elif elftypebyte == 1:
		elftype = 'elfrelocatable'
	elif elftypebyte == 2:
		elftype = 'elfexecutable'
	elif elftypebyte == 3:
		elftype = 'elfdynamic'
	elif elftypebyte == 4:
		elftype = 'elfcore'
	else:
		return (False, None)

	elfresult['elftype'] = elftype

	## check the machine type
	if littleendian:
		elfmachinebyte = struct.unpack('<H', elfbytes[0x12:0x12+2])[0]
	else:
		elfmachinebyte = struct.unpack('>H', elfbytes[0x12:0x12+2])[0]
	if elfmachinebyte in architecturemapping:
		architecture = architecturemapping[elfmachinebyte]
	else:
		architecture = "UNKNOWN"

	elfresult['architecture'] = architecture

	## the start of program headers
	if bit32:
		elfunpackbytes = elfbytes[0x1C:0x20]
	else:
		elfunpackbytes = elfbytes[0x20:0x28]
	if littleendian:
		if bit32:
			startprogramheader = struct.unpack('<I', elfunpackbytes)[0]
		else:
			startprogramheader = struct.unpack('<Q', elfunpackbytes)[0]
	else:
		if bit32:
			startprogramheader = struct.unpack('>I', elfunpackbytes)[0]
		else:
			startprogramheader = struct.unpack('>Q', elfunpackbytes)[0]

	## program header cannot be outside of the file
	if offset + startprogramheader > filesize:
		elffile.close()
		return (False, None)

	## the start of section headers
	if bit32:
		elfunpackbytes = elfbytes[0x20:0x20+4]
	else:
		elfunpackbytes = elfbytes[0x28:0x28+8]
	if littleendian:
		if bit32:
			startsectionheader = struct.unpack('<I', elfunpackbytes)[0]
		else:
			startsectionheader = struct.unpack('<Q', elfunpackbytes)[0]
	else:
		if bit32:
			startsectionheader = struct.unpack('>I', elfunpackbytes)[0]
		else:
			startsectionheader = struct.unpack('>Q', elfunpackbytes)[0]

	## section header cannot be outside of the file
	if offset + startsectionheader > filesize:
		elffile.close()
		return (False, None)

	## the size of the program headers
	if bit32:
		elfunpackbytes = elfbytes[0x2A:0x2A+2]
	else:
		elfunpackbytes = elfbytes[0x36:0x36+2]
	if littleendian:
		programheadersize = struct.unpack('<H', elfunpackbytes)[0]
	else:
		programheadersize = struct.unpack('>H', elfunpackbytes)[0]

	## program header cannot extend past the file
	if offset + startprogramheader + programheadersize > filesize:
		elffile.close()
		return (False, None)

	## the amount of program headers
	if bit32:
		elfunpackbytes = elfbytes[0x2C:0x2C+2]
	else:
		elfunpackbytes = elfbytes[0x38:0x38+2]
	if littleendian:
		numberprogramheaders = struct.unpack('<H', elfunpackbytes)[0]
	else:
		numberprogramheaders = struct.unpack('>H', elfunpackbytes)[0]

	if numberprogramheaders != 0:
		## program header cannot be inside the ELF header
		if offset + startprogramheader + programheadersize < offset + elfheadersize:
			elffile.close()
			return (False, None)

	## the size of the section headers
	if bit32:
		elfunpackbytes = elfbytes[0x2E:0x2E+2]
	else:
		elfunpackbytes = elfbytes[0x3A:0x3A+2]
	if littleendian:
		sectionheadersize = struct.unpack('<H', elfunpackbytes)[0]
	else:
		sectionheadersize = struct.unpack('>H', elfunpackbytes)[0]

	## section header cannot extend past the end of the file
	if offset + startsectionheader + sectionheadersize > filesize:
		elffile.close()
		return (False, None)

	## the amount of section headers
	if bit32:
		elfunpackbytes = elfbytes[0x30:0x30+2]
	else:
		elfunpackbytes = elfbytes[0x3C:0x3C+2]
	if littleendian:
		numbersectionheaders = struct.unpack('<H', elfunpackbytes)[0]
	else:
		numbersectionheaders = struct.unpack('>H', elfunpackbytes)[0]

	## the start of section header index
	if bit32:
		elfunpackbytes = elfbytes[0x32:0x32+2]
	else:
		elfunpackbytes = elfbytes[0x3E:0x3E+2]
	if littleendian:
		sectionheaderindex = struct.unpack('<H', elfunpackbytes)[0]
	else:
		sectionheaderindex = struct.unpack('>H', elfunpackbytes)[0]

	## section header cannot be inside the ELF header
	if numbersectionheaders != 0:
		if offset + startsectionheader + sectionheadersize < offset + elfheadersize:
			elffile.close()
			return (False, None)

	## First process the program header table
	brokenelf = False
	maxendofprogramsegments = 0
	for i in range(0,numberprogramheaders):
		elffile.seek(offset + startprogramheader + i*programheadersize)
		elfbytes = elffile.read(programheadersize)
		if len(elfbytes) != programheadersize:
			brokenelf = True
			break
		## first the segmenttype
		if littleendian:
			segmenttype = struct.unpack('<I', elfbytes[:4])[0]
		else:
			segmenttype = struct.unpack('>I', elfbytes[:4])[0]

		## PT_NULL is unused, so ignore
		if segmenttype == 0:
			continue

		## then the offset in the file
		if littleendian:
			if bit32:
				segmentoffset = struct.unpack('<I', elfbytes[4:8])[0]
			else:
				segmentoffset = struct.unpack('<Q', elfbytes[8:16])[0]
		else:
			if bit32:
				segmentoffset = struct.unpack('>I', elfbytes[4:8])[0]
			else:
				segmentoffset = struct.unpack('>Q', elfbytes[8:16])[0]

		## segment cannot be outside of the file
		if offset + segmentoffset > filesize:
			brokenelf = True
			break

		## then the virtual address in memory (skip for now) -- 4 bytes (32 bit) or 8 bytes
		## then the physical address in memory (skip for now) -- 4 bytes (32 bit) or 8 bytes
		## then the size in bytes in the file image
		if littleendian:
			if bit32:
				segmentsize = struct.unpack('<I', elfbytes[16:20])[0]
			else:
				segmentsize = struct.unpack('<Q', elfbytes[32:40])[0]
		else:
			if bit32:
				segmentsize = struct.unpack('>I', elfbytes[16:20])[0]
			else:
				segmentsize = struct.unpack('>Q', elfbytes[32:40])[0]

		## segment cannot extend past the end of the file
		if offset + segmentoffset + segmentsize > filesize:
			brokenelf = True
			break
		maxendofprogramsegments = max(offset + segmentoffset + segmentsize, maxendofprogramsegments)

		## then the size in bytes in memory image
		if littleendian:
			if bit32:
				memsegmentsize = struct.unpack('<I', elfbytes[16:20])[0]
			else:
				memsegmentsize = struct.unpack('<Q', elfbytes[32:40])[0]
		else:
			if bit32:
				memsegmentsize = struct.unpack('>I', elfbytes[16:20])[0]
			else:
				memsegmentsize = struct.unpack('>Q', elfbytes[32:40])[0]
		## PT_LOAD
		if segmenttype == 1:
			## memory size cannot be smaller than the
			## segment to be loaded into memory.
			if memsegmentsize < segmentsize:
				brokenelf = True
				break
		## then the segment dependent flags (skip for now) -- 4 bytes
		## then the alignment
		if littleendian:
			if bit32:
				alignment = struct.unpack('<I', elfbytes[28:32])[0]
			else:
				alignment = struct.unpack('<I', elfbytes[52:60])[0]

		else:
			if bit32:
				alignment = struct.unpack('>I', elfbytes[28:32])[0]
			else:
				alignment = struct.unpack('>I', elfbytes[52:60])[0]
		if alignment != 0 and alignment != 1:
			## alignment has to be a power of 2
			if alignment != pow(2,int(math.log(alignment, 2))):
				brokenelf = True
				break
			## TODO: check if certain parts are properly aligned

	if brokenelf:
		elffile.close()
		return (False, None)

	dynamic = False

	sections = {}

	## process the section headers
	maxendofsection = 0
	dynamiccount = 0
	for i in xrange(0,numbersectionheaders):
		elffile.seek(offset+startsectionheader + i * sectionheadersize)
		elfbytes = elffile.read(sectionheadersize)
		if len(elfbytes) != sectionheadersize:
			elffile.close()
			return (False, None)
		if littleendian:
			sh_name = struct.unpack('<I', elfbytes[0:4])[0]
		else:
			sh_name = struct.unpack('>I', elfbytes[0:4])[0]
		if littleendian:
			sh_type = struct.unpack('<I', elfbytes[4:8])[0]
		else:
			sh_type = struct.unpack('>I', elfbytes[4:8])[0]
		if sh_type == 6:
			dynamiccount += 1
		## then the flags (4 byte or 8 byte) -- skip for now
		if littleendian:
			if bit32:
				sh_flags = struct.unpack('<I', elfbytes[8:12])[0]
			else:
				sh_flags = struct.unpack('<Q', elfbytes[8:16])[0]
		else:
			if bit32:
				sh_flags = struct.unpack('>I', elfbytes[8:12])[0]
			else:
				sh_flags = struct.unpack('>Q', elfbytes[8:16])[0]
	
		## then the virtual address (4 byte or 8 byte) -- skip for now
		if littleendian:
			if bit32:
				sh_addr = struct.unpack('<I', elfbytes[12:16])[0]
			else:
				sh_addr = struct.unpack('<Q', elfbytes[16:24])[0]
		else:
			if bit32:
				sh_addr = struct.unpack('>I', elfbytes[12:16])[0]
			else:
				sh_addr = struct.unpack('>Q', elfbytes[16:24])[0]
		## then the offset
		if littleendian:
			if bit32:
				sectionoffset = struct.unpack('<I', elfbytes[16:20])[0]
			else:
				sectionoffset = struct.unpack('<Q', elfbytes[24:32])[0]
		else:
			if bit32:
				sectionoffset = struct.unpack('>I', elfbytes[16:20])[0]
			else:
				sectionoffset = struct.unpack('>Q', elfbytes[24:32])[0]

		## section offset cannot be outside of the file
		if offset + sectionoffset > filesize:
			brokenelf = True
			break

		## then the size in bytes in the file image
		if littleendian:
			if bit32:
				sectionsize = struct.unpack('<I', elfbytes[20:24])[0]
			else:
				sectionsize = struct.unpack('<Q', elfbytes[32:40])[0]
		else:
			if bit32:
				sectionsize = struct.unpack('>I', elfbytes[20:24])[0]
			else:
				sectionsize = struct.unpack('>Q', elfbytes[32:40])[0]

		## segment cannot extend past the end of the file.
		## This check only makes sense if the section has a different
		## type than NOBITS
		if sh_type != 8:
			if offset + sectionoffset + sectionsize > filesize:
				brokenelf = True
				break
			maxendofsection = max(offset + sectionoffset + sectionsize, maxendofsection)

		sections[i] = {'sectionoffset': sectionoffset, 'sectionsize': sectionsize, 'nameoffset': sh_name, 'sectiontype': sh_type}

	if brokenelf:
		elffile.close()
		return (False, None)

	## dynamic count cannot be larger than 1
	if dynamiccount == 1:
		dynamic = True

	## for each section find the name in the table with section names
	sectionnames = []
	if sectionheaderindex in sections:
		elffile.seek(sections[sectionheaderindex]['sectionoffset'])
		sectionnamebytes = elffile.read(sections[sectionheaderindex]['sectionsize'])
		sectionnames = sectionnamebytes.split('\x00')
		for i in sections:
			endofsectionname = sectionnamebytes.find('\x00', sections[i]['nameoffset'])
			sections[i]['name'] = sectionnamebytes[sections[i]['nameoffset']:endofsectionname]

	## finally close the file
	elffile.close()

	## Now some extra checks so files can be tagged as ELF
	if maxendofprogramsegments == filesize:
		iself = True
		totalsize = filesize
	elif maxendofsection == filesize:
		iself = True
		totalsize = filesize
	else:
		## This does not work well for some Linux kernel modules as well as other files
		## (architecture dependent?)
		## One architecture where this sometimes seems to happen is ARM.
		totalsize = startsectionheader + sectionheadersize * numbersectionheaders

		## there are files where the number of section headers is zero, but
		## which are valid ELF files. An example is the bootloader on certain
		## Android devices. TODO.
		if totalsize == 0:
			pass
		if totalsize == filesize:
			iself = True
		else:
			## If it is a signed kernel module then the key is appended to the ELF data
			elffile = open(filename, 'rb')
			elffile.seek(-28, os.SEEK_END)
			elfbytes = elffile.read()
			if elfbytes == "~Module signature appended~\n":
				## The metadata of the signing data can be found in 12 bytes
				## preceding the 'magic'
				## According to 'scripts/sign-file' in the Linux kernel
				## the last 4 bytes are the size of the signature data
				## three bytes before that are 0x00
				## The byte before that is the length of the key identifier
				## The byte before that is the length of the "signer's name"
				totalsiglength = 40
				elffile.seek(-40, os.SEEK_END)
				elfbytes = elffile.read(12)
				signaturelength = struct.unpack('>I', elfbytes[-4:])[0]
				totalsiglength += signaturelength
				keyidentifierlen = ord(elfbytes[4])
				signernamelen = ord(elfbytes[3])
				totalsiglength += keyidentifierlen
				totalsiglength += signernamelen
				if totalsiglength + totalsize == filesize:
					iself = True
				totalsize += totalsiglength
			elffile.close()
			## check if the max end of section happens to be later than
			## the totalsize, as this happens as well in non-stripped binaries
			totalsize = max(maxendofsection, totalsize)

	elfresult['dynamic'] = dynamic
	elfresult['sectionnames'] = sectionnames
	elfresult['sections'] = sections
	elfresult['size'] = totalsize

	if not iself:
		return (False, elfresult)

	return (True, elfresult)
