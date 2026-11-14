"""Reproduce the received-binary review offline; Android binaries are never executed.

Requires pyelftools 0.32 and Unicorn 2.1.4. Supply private OEM files locally;
no binary, private pathname or raw device log is included in the report.
"""
import argparse,struct,io,json,hashlib
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
import patch_surfaceflinger as patch
SF=None
HWC=None
COMPOSER_SHA256='39b509d355bd642f57a111521df31ef817c7938fbf7a736dbe0cfad255d51c3a'
def require(condition, message):
 if not condition:raise ValueError(message)
def base(data):
 e=ELFFile(io.BytesIO(data));u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
 u.mem_map(0,0x1000000)
 for s in e.iter_segments():
  if s['p_type']=='PT_LOAD':u.mem_write(s['p_vaddr'],s.data())
 u.mem_map(0x2000000,0x100000);u.mem_map(0x3000000,0x1000)
 u.reg_write(UC_ARM64_REG_SP,0x20f0000);u.reg_write(UC_ARM64_REG_X30,0x3000000)
 return u
def put(u,addr,fmt,*values):u.mem_write(addr,struct.pack('<'+fmt,*values))
def group_from_composer(width,height,config,attribute=7):
 u=base(HWC);obj=0x2000000;node=0x2002000;out=0x2003000;tls=0x2004000
 u.reg_write(UC_ARM64_REG_TPIDR_EL0,tls)
 put(u,obj+0x1b0,'Q',node);put(u,obj+0x1a8,'Q',node)
 put(u,node+0x10,'Q',obj+0x1b0);put(u,node+0x1c,'I',config)
 put(u,node+0x20,'IIff',width,height,409.432831,406.399994)
 put(u,node+0x38,'I',8333333 if config==0 else 16666666)
 table=bytes(u.mem_read(0x1f240,0xcf));idx=next(i for i,b in enumerate(table) if b&1)
 put(u,obj,'Q',0x8d150+32*idx)
 u.reg_write(UC_ARM64_REG_X0,obj);u.reg_write(UC_ARM64_REG_X1,config)
 u.reg_write(UC_ARM64_REG_X2,attribute);u.reg_write(UC_ARM64_REG_X3,out)
 u.emu_start(0x64784,0x3000000,count=1000)
 require(u.reg_read(UC_ARM64_REG_PC)==0x3000000, 'Function did not return within instruction budget')
 return {'return_code':u.reg_read(UC_ARM64_REG_W0),'group':struct.unpack('<i',u.mem_read(out,4))[0]}
def predicate(group,default_group,patched=False,fps=120,default_fps=120,width=1080,default_width=1080,allow=False,physical=(0,3.4028234663852886e38),render=(0,3.4028234663852886e38),feature_flag=False):
 u=base(patch.transform(SF) if patched else SF);capture=0x2000000;mode=0x2001000;default=0x2003000
 put(u,capture+8,'QQQQ',0x2002000,0x2004000,0x2006000,0x2007000)
 put(u,0x2002000,'Q',default);put(u,0x2004000,'Q',0x2005000)
 put(u,0x2005004,'B',int(allow))
 for p,w,f,g in [(mode,width,fps,group),(default,default_width,default_fps,default_group)]:
  put(u,p+0x10,'IIff',w,2400,f,f)
  put(u,p+0x28,'ffi',409.432831,406.399994,g)
 for off,val in [(0,physical[0]),(0x10,physical[1]),(0x20,render[0]),(0x30,render[1])]:put(u,0x2006000+off,'f',val)
 u.reg_write(UC_ARM64_REG_X0,capture);u.reg_write(UC_ARM64_REG_X1,mode)
 def hook(uc,pc,size,_):
  ins=struct.unpack('<I',uc.mem_read(pc,4))[0]
  if pc in (0x49b8b8,0x49b9b0):uc.reg_write(UC_ARM64_REG_PC,pc+4)
  elif ins>>26==0b100101:
   if pc not in (0x49b8e0,0x49b8e4):raise RuntimeError('Unexpected external call '+hex(pc))
   uc.reg_write(UC_ARM64_REG_W0,int(feature_flag));uc.reg_write(UC_ARM64_REG_PC,pc+4)
 u.hook_add(UC_HOOK_CODE,hook)
 u.emu_start(0x49b8b8,0x3000000,count=1000)
 require(u.reg_read(UC_ARM64_REG_PC)==0x3000000, 'Function did not return within instruction budget')
 return bool(u.reg_read(UC_ARM64_REG_W0))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--surfaceflinger',type=Path,required=True)
parser.add_argument('--composer',type=Path,required=True)
args=parser.parse_args()
SF=args.surfaceflinger.read_bytes();HWC=args.composer.read_bytes()
patch.verify(SF)
if len(HWC)!=610736 or hashlib.sha256(HWC).hexdigest()!=COMPOSER_SHA256:
 raise ValueError('Exact composer size/SHA256 differs')
rows=[]
for c in (0,1):
 result=group_from_composer(1080,2400,c)
 require(result==dict(return_code=0,group=1080), 'Unexpected composer group result: '+repr(result))
 rows.append({'composer_config':c,**result})
# The shared width/group return block must not be mistaken for a guessed enum.
for attr,expected in ((1,1080),(2,2400),(3,8333333)):
 require(group_from_composer(1080,2400,0,attr)==dict(return_code=0,group=expected), 'Composer fixture attribute mismatch')

for label,parameters,expected_original,expected_patched in [
 ('120Hz same group1080',dict(group=1080,default_group=1080),False,True),
 ('60Hz same group1080',dict(group=1080,default_group=1080,fps=60),False,True),
 ('different group56',dict(group=56,default_group=1080),True,False),
 ('different group1081',dict(group=1081,default_group=1080),False,False),
 ('different resolution',dict(group=1080,default_group=1080,width=720),False,False),
 ('physical out of range',dict(group=1080,default_group=1080,physical=(30,90)),False,False),
 ('render out of range',dict(group=1080,default_group=1080,render=(30,90)),False,False),
 ('allow group switching',dict(group=1081,default_group=1080,allow=True),True,True),
 ('group0',dict(group=0,default_group=0),True,True),
 ('group255',dict(group=255,default_group=255),True,True),
 ('group256',dict(group=256,default_group=256),False,True),
 ('group minus1',dict(group=-1,default_group=-1),False,True),
]:
 for flag in (False,True):
  original=predicate(**parameters,feature_flag=flag)
  patched=predicate(**parameters,patched=True,feature_flag=flag)
  require((original,patched)==(expected_original,expected_patched), 'Predicate mismatch: '+repr((label,flag,original,patched)))
  rows.append({'case':label,'feature_flag':flag,'original':original,'patched':patched})
print(json.dumps({'scope':'Actual received function instructions; synthetic config map/mode objects; two external callees stubbed, tested with returned flag false and true; PAC skipped; no Android/device boot simulation','surfaceflinger_original_sha256':patch.ORIGINAL_SHA256,'surfaceflinger_patched_sha256':patch.PATCHED_SHA256,'composer_sha256':COMPOSER_SHA256,'results':rows},indent=2))
