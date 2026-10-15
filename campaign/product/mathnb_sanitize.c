/* SPDX-License-Identifier: MIT
 * Independent malformed-input/spec stress. Run under ASan/UBSan on host. */
#include "mathnb.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
static uint32_t rng=24;
static uint32_t next(void) { rng^=rng<<13; rng^=rng>>17; rng^=rng<<5; return rng; }
static uint16_t fb[256*192+2];
int main(void) {
    mnb_spec s; mnb_values v;
    char query[256];
    const char *examples[]={"plot x squared from -5 to 5","graph sin x","show bars for 3, 8, 2, 6","table of 2^n for n 1 to 8"};
    for (int i=0;i<4;i++) {
        assert(mnb_parse(examples[i],&s)==1);
        assert(mnb_evaluate(&s,&v));
        fb[0]=123;fb[256*192+1]=321;
        assert(mnb_render(&s,&v,fb+1));assert(fb[0]==123&&fb[256*192+1]==321);
    }
    for (int i=0;i<30000;i++) {
        size_t len=next()%sizeof(query);
        for (size_t j=0;j<len;j++) query[j]=(char)(1+next()%126);
        query[len]=0;
        if (i%2==0 && len>=5) memcpy(query,"plot ",5);
        if (mnb_parse(query,&s)==1 && mnb_evaluate(&s,&v)) assert(mnb_render(&s,&v,fb+1));
        for (size_t j=0;j<sizeof(s);j++) ((unsigned char *)&s)[j]=(unsigned char)next();
        mnb_evaluate(&s,&v);mnb_render(&s,&v,fb+1);
        mnb_parse("plot x+1",&s);
        s.ast[2].op=(uint8_t)next();s.ast[2].left=(uint8_t)next();s.ast[2].right=(uint8_t)next();
        mnb_evaluate(&s,&v);mnb_render(&s,&v,fb+1);
    }
    puts("30000 malformed queries/specs + 4 canary renders: PASS");
    return 0;
}
