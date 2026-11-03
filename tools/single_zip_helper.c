/* Read one ZIP_STORED member through bounded 64-bit offsets. No device writes.
 * SPDX-License-Identifier: MIT
 * Build: aarch64-linux-android29-clang -D_FILE_OFFSET_BITS=64 -static -Os -s
 *        -Wall -Wextra -Werror single_zip_helper.c -o r8q-zipread
 */
#define _POSIX_C_SOURCE 200809L
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
_Static_assert(sizeof(off_t)>=8,"64-bit file offsets are required");

static int fd;
static uint64_t archive_size;
static void die(const char *message) { fprintf(stderr,"r8q-zipread: %s\n",message); exit(2); }
static uint16_t u16(const unsigned char *p) { return (uint16_t)(p[0]|(uint16_t)p[1]<<8); }
static uint32_t u32(const unsigned char *p) { return (uint32_t)u16(p)|(uint32_t)u16(p+2)<<16; }
static uint64_t u64(const unsigned char *p) { return (uint64_t)u32(p)|(uint64_t)u32(p+4)<<32; }
static void read_at(uint64_t offset, void *data, size_t size) {
    if (offset>archive_size || size>archive_size-offset || offset>INT64_MAX) die("read outside archive");
    unsigned char *p=data;
    while(size) {
        ssize_t got=pread(fd,p,size,(off_t)offset);
        if(got<0 && errno==EINTR)continue;
        if(got<=0)die("short or failed archive read");
        offset+=(size_t)got;p+=got;size-=(size_t)got;
    }
}
static uint32_t crc_table[256];
static void crc_init(void) {
    for(unsigned i=0;i<256;i++) {
        uint32_t c=i;
        for(unsigned j=0;j<8;j++)c=(c>>1)^((c&1)?UINT32_C(0xedb88320):0);
        crc_table[i]=c;
    }
}
static uint32_t crc_update(uint32_t crc,const unsigned char *p,size_t size) {
    while(size--)crc=crc_table[(crc^*p++)&255]^(crc>>8);
    return crc;
}
struct entry { uint64_t size, compressed, local; uint32_t crc; uint16_t flags,method; };
static void zip64_extra(const unsigned char *extra,size_t length,
                        uint64_t *size,uint64_t *compressed,uint64_t *local,int need_local) {
    int found=0,need_size=*size==UINT32_MAX,need_compressed=*compressed==UINT32_MAX;
    int need_offset=need_local && *local==UINT32_MAX;
    int got_size=0,got_compressed=0,got_offset=0;
    while(length) {
        if(length<4)die("truncated ZIP extra field");
        unsigned tag=u16(extra),n=u16(extra+2);extra+=4;length-=4;
        if(n>length)die("ZIP extra field exceeds header");
        if(tag==1) {
            if(found++)die("duplicate ZIP64 extra field");
            const unsigned char *p=extra;size_t left=n;
            if(need_size) {if(left<8)die("missing ZIP64 size");*size=u64(p);p+=8;left-=8;got_size=1;}
            if(need_compressed) {if(left<8)die("missing ZIP64 compressed size");*compressed=u64(p);p+=8;left-=8;got_compressed=1;}
            if(need_offset) {if(left<8)die("missing ZIP64 local offset");*local=u64(p);got_offset=1;}
        }
        extra+=n;length-=n;
    }
    if((need_size&&!got_size) || (need_compressed&&!got_compressed) || (need_offset&&!got_offset))die("ZIP64 values missing");
}
static struct entry lookup(const char *wanted,uint64_t *central_start) {
    if(archive_size<22)die("archive is shorter than EOCD");
    size_t tail_size=archive_size>65557?65557:(size_t)archive_size;
    unsigned char *tail=malloc(tail_size);if(!tail)die("out of memory");
    uint64_t tail_offset=archive_size-tail_size;read_at(tail_offset,tail,tail_size);
    size_t pos=tail_size-22;int found=0;
    do {if(u32(tail+pos)==UINT32_C(0x06054b50) && pos+22+u16(tail+pos+20)==tail_size) {found=1;break;}}while(pos--);
    if(!found)die("EOCD not found at end of archive");
    const unsigned char *e=tail+pos;
    if(u16(e+4)||u16(e+6)||u16(e+8)!=u16(e+10))die("multi-disk ZIP unsupported");
    uint64_t count=u16(e+10),length=u32(e+12),start=u32(e+16),eocd=tail_offset+pos;
    int need_zip64=count==UINT16_MAX || length==UINT32_MAX || start==UINT32_MAX;
    unsigned char locator[20];int has_zip64=need_zip64;
    /* Writers may emit ZIP64 before any classic field overflows (Python does
     * so above 2 GiB). Its locator is still authoritative when present between
     * the central directory and EOCD. Do not mistake central comment bytes in
     * an otherwise ordinary ZIP for an optional locator. */
    if(!need_zip64 && eocd>=20 && (start>eocd || length!=eocd-start)) {
        read_at(eocd-20,locator,sizeof(locator));
        has_zip64=u32(locator)==UINT32_C(0x07064b50);
    }
    if(has_zip64) {
        unsigned char z[56];
        if(eocd<20)die("ZIP64 locator missing");
        read_at(eocd-20,locator,20);
        if(u32(locator)!=UINT32_C(0x07064b50)||u32(locator+4)||u32(locator+16)!=1)die("invalid ZIP64 locator");
        uint64_t zpos=u64(locator+8);read_at(zpos,z,56);
        if(u32(z)!=UINT32_C(0x06064b50)||u64(z+4)!=44||u32(z+16)||u32(z+20)||u64(z+24)!=u64(z+32))die("invalid ZIP64 EOCD");
        if(zpos>eocd-20 || 56!=eocd-20-zpos)die("ZIP64 EOCD bounds differ");
        if((count!=UINT16_MAX && count!=u64(z+32)) ||
           (length!=UINT32_MAX && length!=u64(z+40)) ||
           (start!=UINT32_MAX && start!=u64(z+48)))die("classic/ZIP64 EOCD values differ");
        count=u64(z+32);length=u64(z+40);start=u64(z+48);eocd=zpos;
    }
    free(tail);
    if(!count||count>4096||start>eocd||length!=eocd-start)die("central directory bounds invalid");
    *central_start=start;
    uint64_t cursor=start,end=start+length;struct entry answer={0};unsigned matches=0;
    for(uint64_t i=0;i<count;i++) {
        unsigned char h[46];if(cursor>end || sizeof(h)>end-cursor)die("central header out of bounds");
        read_at(cursor,h,sizeof(h));if(u32(h)!=UINT32_C(0x02014b50))die("bad central header signature");
        unsigned namesize=u16(h+28),extrasize=u16(h+30),comment=u16(h+32);
        if(!namesize||namesize>1024||u16(h+34))die("invalid central filename/disk");
        uint64_t total=46+(uint64_t)namesize+extrasize+comment;
        if(total>end-cursor)die("central variable fields out of bounds");
        unsigned char *fields=malloc((size_t)namesize+extrasize+1);if(!fields)die("out of memory");
        read_at(cursor+46,fields,(size_t)namesize+extrasize);fields[namesize+extrasize]=0;
        if(memchr(fields,0,namesize))die("embedded NUL filename");
        if(strlen(wanted)==namesize && !memcmp(fields,wanted,namesize)) {
            if(matches++)die("duplicate requested member");
            answer.flags=u16(h+8);answer.method=u16(h+10);answer.crc=u32(h+16);
            answer.compressed=u32(h+20);answer.size=u32(h+24);answer.local=u32(h+42);
            zip64_extra(fields+namesize,extrasize,&answer.size,&answer.compressed,&answer.local,1);
        }
        free(fields);cursor+=total;
    }
    if(cursor!=end||matches!=1)die("missing member or trailing central data");
    if((answer.flags&~UINT16_C(0x0800)) || answer.method!=0 || answer.size!=answer.compressed || !answer.size || answer.size>UINT64_C(1073741824))die("requested member is not a bounded stored entry");
    return answer;
}
int main(int argc,char **argv) {
    int size_only=argc==4 && !strcmp(argv[1],"--size");
    if(argc==2 && !strcmp(argv[1],"--version")){puts("r8q-zipread 2 ZIP64 stored, 64-bit pread, CRC32");return 0;}
    if((!size_only&&argc!=3)||(size_only&&argc!=4))die("usage: r8q-zipread [--size] ZIP MEMBER");
    const char *path=argv[size_only?2:1],*wanted=argv[size_only?3:2];
    if(strncmp(wanted,"payloads/",9) || !wanted[9] || strchr(wanted+9,'/') || strstr(wanted,".."))die("only named payload members may be streamed");
    fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)die("cannot open local ZIP");
    struct stat st;if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<0)die("ZIP must be a regular file");
    archive_size=(uint64_t)st.st_size;uint64_t central;struct entry entry=lookup(wanted,&central);
    unsigned char local[30];read_at(entry.local,local,sizeof(local));
    if(u32(local)!=UINT32_C(0x04034b50)||u16(local+6)!=entry.flags||u16(local+8)!=entry.method||u32(local+14)!=entry.crc)die("local/central header mismatch");
    unsigned name_size=u16(local+26),extra_size=u16(local+28);
    if(name_size!=strlen(wanted))die("local filename length differs");
    unsigned char *fields=malloc((size_t)name_size+extra_size);if(!fields)die("out of memory");
    read_at(entry.local+30,fields,(size_t)name_size+extra_size);
    if(memcmp(fields,wanted,name_size))die("local filename differs");
    uint64_t size=u32(local+22),compressed=u32(local+18),unused=0;
    zip64_extra(fields+name_size,extra_size,&size,&compressed,&unused,0);free(fields);
    if(size!=entry.size||compressed!=entry.compressed)die("local/central sizes differ");
    uint64_t offset=entry.local+30+name_size+extra_size;
    if(offset>central||entry.size>central-offset)die("member overlaps central directory");
    if(size_only){printf("%" PRIu64 "\n",entry.size);close(fd);return 0;}
    unsigned char buffer[65536];uint64_t remaining=entry.size;uint32_t crc=UINT32_MAX;crc_init();
    while(remaining) {
        size_t n=remaining>sizeof(buffer)?sizeof(buffer):(size_t)remaining;read_at(offset,buffer,n);
        crc=crc_update(crc,buffer,n);size_t done=0;
        while(done<n){ssize_t w=write(STDOUT_FILENO,buffer+done,n-done);if(w<0&&errno==EINTR)continue;if(w<=0)die("output write failed");done+=(size_t)w;}
        offset+=n;remaining-=n;
    }
    if((crc^UINT32_MAX)!=entry.crc) {
        fprintf(stderr,"r8q-zipread: member CRC32 mismatch: member=%s data_offset=%" PRIu64
                " member_bytes=%" PRIu64 " archive_bytes=%" PRIu64
                " expected=%08" PRIx32 " observed=%08" PRIx32 "\n",
                wanted,offset-entry.size,entry.size,archive_size,entry.crc,crc^UINT32_MAX);
        exit(2);
    }
    if(close(fd))die("archive close failed");
    return 0;
}
