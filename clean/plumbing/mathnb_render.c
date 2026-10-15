/* SPDX-License-Identifier: MIT */
#include "mathnb.h"
#include <stdio.h>
#include <string.h>
/* Same font as clean/ui. Keep renderer independent of UI state. */
extern const uint8_t chatds_ui_font[95][8];
#define BG 0x9401
#define FG 0xf79c
#define GRID 0xc5cd
#define INK 0xff0e
static void pixel(uint16_t *f,int x,int y,uint16_t c) { if (x>=0&&x<256&&y>=0&&y<192) f[y*256+x]=c; }
static void line(uint16_t *f,int x,int y,int u,int v,uint16_t c) {
    int dx=u>x?u-x:x-u, sx=x<u?1:-1, dy=v>y?y-v:v-y, sy=y<v?1:-1, err=dx+dy;
    for (;;) { pixel(f,x,y,c); if (x==u&&y==v) break; int e=2*err; if (e>=dy) { err+=dy;x+=sx; } if (e<=dx) { err+=dx;y+=sy; } }
}
static void text(uint16_t *f,int x,int y,const char *s) {
    for (;*s&&x<250;s++,x+=6) {
        unsigned c=(unsigned char)*s;
        if (c<32||c>126) c='?';
        for (int row=0;row<8;row++) for (int col=0;col<5;col++) if (chatds_ui_font[c-32][row]&(16>>col)) pixel(f,x+col,y+row,FG);
    }
}
static void fmt(int32_t v,char *s) {
    int64_t a=v<0?-(int64_t)v:v;
    snprintf(s,24,"%s%ld.%04ld",v<0?"-":"",(long)(a/MNB_SCALE),(long)(a%MNB_SCALE));
    size_t n=strlen(s); while (n&&s[n-1]=='0') s[--n]=0; if (n&&s[n-1]=='.') s[n-1]=0;
}
static int map(int32_t v,int32_t lo,int32_t hi,int start,int width) { return start+(int)((int64_t)(v-lo)*width/(hi-lo)); }
int mnb_render(const mnb_spec *s,const mnb_values *v,uint16_t *f) {
    mnb_values check;
    if (!mnb_evaluate(s,&check)) return 0;
    for (int i=0;i<s->points;i++) if (check.x[i]!=v->x[i]||check.y[i]!=v->y[i]) return 0;
    for (int i=0;i<256*192;i++) f[i]=BG;
    text(f,5,3,s->kind==MNB_PLOT?"pocket math | plot":s->kind==MNB_BAR?"pocket math | bars":"pocket math | table");
    char a[24],b[24];
    if (s->kind==MNB_TABLE) {
        text(f,12,16,"x / n"); text(f,104,16,"value"); line(f,10,26,244,26,GRID);
        for (int i=0;i<s->points;i++) { fmt(v->x[i],a);fmt(v->y[i],b);text(f,12,29+10*i,a);text(f,104,29+10*i,b); }
        return 1;
    }
    int32_t lo=0,hi=0;
    for (int i=0;i<s->points;i++) { if (v->y[i]<lo) lo=v->y[i]; if (v->y[i]>hi) hi=v->y[i]; }
    if (lo==hi) { lo-=MNB_SCALE;hi+=MNB_SCALE; }
    /* Five bounded ticks spanning the actual auto-scaled extent. */
    for (int i=0;i<=4;i++) {
        int y=170-i*34; int32_t tick=lo+(int32_t)((int64_t)(hi-lo)*i/4);
        line(f,54,y,246,y,GRID);fmt(tick,a);text(f,1,y-3,a);
    }
    int zero=map(0,lo,hi,170,-136);
    line(f,54,zero,246,zero,FG);
    if (s->kind==MNB_PLOT) {
        int axis=s->lo<=0&&s->hi>=0?map(0,s->lo,s->hi,54,192):54;
        line(f,axis,34,axis,170,FG);
        for (int i=0;i<=4;i++) {
            int x=54+i*48; int32_t tick=s->lo+(int32_t)((int64_t)(s->hi-s->lo)*i/4);
            line(f,x,170,x,174,FG);fmt(tick,a);text(f,x-(int)strlen(a)*3,180,a);
        }
        for (int i=1;i<s->points;i++) line(f,map(v->x[i-1],s->lo,s->hi,54,192),map(v->y[i-1],lo,hi,170,-136),map(v->x[i],s->lo,s->hi,54,192),map(v->y[i],lo,hi,170,-136),INK);
    } else {
        line(f,54,34,54,170,FG);
        int w=192/s->points;
        for (int i=0;i<s->points;i++) {
            int y=map(v->y[i],lo,hi,170,-136);
            for (int x=56+i*w;x<54+(i+1)*w-1;x++) line(f,x,zero,x,y,INK);
            snprintf(a,sizeof a,"%d",i+1);text(f,54+i*w+w/2-3,180,a);
            if (s->points<=8) { fmt(v->y[i],a);text(f,54+i*w,y>zero?y+2:y-10,a); }
        }
    }
    return 1;
}
