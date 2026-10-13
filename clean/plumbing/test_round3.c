/* SPDX-License-Identifier: MIT
 * Round3 standalone parity/fuzz driver. No product/include dependency changes. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include "round3.h"

static cds_round3 model;
static cds_router_work work;
static uint32_t seed;
static uint32_t rnd(void) { seed = seed * 1664525u + 1013904223u; return seed; }
static void load(cds_router *r, const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f || fseek(f, 0, SEEK_END)) exit(2);
    long n = ftell(f);
    if (n < 64 || n > 49152 || fseek(f, 0, SEEK_SET)) exit(2);
    unsigned char *b = malloc((size_t)n);
    if (!b || fread(b, 1, (size_t)n, f) != (size_t)n) exit(2);
    fclose(f);
    if (cds_router_open(r,b,(size_t)n,1) || r->kind || r->nheads != 1) exit(2);
    /* Deliberately kept alive throughout inference, freed on exit below. */
}
static int decode(char *s) {
    int n=0;
    for (int i=0; s[i]; i++) {
        if (s[i]=='\\' && s[i+1]) {
            i++;
            if (s[i]=='n') s[n++]='\n';
            else if (s[i]=='t') s[n++]='\t';
            else if (s[i]=='r') s[n++]='\r';
            else if (s[i]=='x' && s[i+1] && s[i+2]) {
                char hex[3]={s[i+1],s[i+2],0}; s[n++]=(char)strtol(hex,NULL,16); i+=2;
            } else s[n++]=s[i];
        } else s[n++]=s[i];
    }
    s[n]=0; return n;
}
static void esc(const char *s) {
    for (;*s;s++) {
        unsigned char c=(unsigned char)*s;
        if (c=='\\') fputs("\\\\",stdout);
        else if (c<32 || c>126) printf("\\x%02x",c);
        else putchar(c);
    }
}
static void fuzz(int count) {
    char q[520],out[256]; cds_round3_text result;
    for (int i=0;i<count;i++) {
        int n=(int)(rnd()%sizeof(q)); if (n>=519) n=519;
        for (int j=0;j<n;j++) q[j]=(char)(1+rnd()%255);
        q[n]=0;
        int32_t margin=0;
        cds_round3_act(&model,&work,q,i%2,&margin);
        cds_round3_textop(&model,&work,q,&result,out,sizeof out);
        /* Printable inputs drive tokenizer/tagging paths as well. */
        n=(int)(rnd()%160);
        for (int j=0;j<n;j++) q[j]=(char)(32+rnd()%95);
        q[n]=0;
        cds_round3_act(&model,&work,q,0,&margin);
        cds_round3_textop(&model,&work,q,&result,out,sizeof out);
        /* Existing literal executor seam, all operations and output bounds. */
        n=1+(int)(rnd()%127);
        for (int j=0;j<n;j++) q[j]=(char)(32+rnd()%95);
        q[n]=0;
        cds_textops_literal(i%TO_NOPS,q,(int)(rnd()%14),"a","longer",out,sizeof out);
    }
}
int main(int argc,char **argv) {
    if (argc<7) return 2;
    load(&model.act,argv[1]); load(&model.op,argv[2]); load(&model.tag,argv[3]);
    if (model.act.nroutes!=11 || model.op.nroutes!=TO_NOPS+1 || model.tag.nroutes!=5) return 2;
    model.act_threshold=(int32_t)strtol(argv[4],NULL,10);
    model.op_threshold=(int32_t)strtol(argv[5],NULL,10);
    model.tag_threshold=(int32_t)strtol(argv[6],NULL,10);
    if (argc==10 && !strcmp(argv[7],"--fuzz")) {
        seed=(uint32_t)strtoul(argv[8],NULL,10); fuzz(atoi(argv[9])); puts("fuzz OK");
    } else {
        char line[4096];
        while (fgets(line,sizeof line,stdin)) {
            line[strcspn(line,"\n")]=0;
            char *q=strchr(line,'\t'); if (!q) return 2;
            *q++=0; int blocked=atoi(line); decode(q);
            cds_route_result raw; cds_router_run(&model.act,&work,q,&raw);
            int32_t margin=0;
            int act=cds_round3_act(&model,&work,q,blocked,&margin);
            cds_round3_text result; char out[256];
            int hit=cds_round3_textop(&model,&work,q,&result,out,sizeof out);
            printf("%u\t%d\t%d\t%d\t",raw.route,raw.margin,act,hit);
            if (hit) printf("%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t",
                result.op,result.start,result.end,result.xstart,result.xend,result.ystart,result.yend,
                result.repeat,result.margin,result.tag_margin);
            esc(hit?out:""); putchar('\n');
        }
    }
    /* Flat sidecar body starts at offset 64. */
    free((void *)(model.act.route_handler-64));
    free((void *)(model.op.route_handler-64));
    free((void *)(model.tag.route_handler-64));
    return 0;
}
