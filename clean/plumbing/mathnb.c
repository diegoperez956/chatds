/* SPDX-License-Identifier: MIT
 * Deterministic integer prototype. Decimal scale/half-away rounding match calc.c.
 * Every public spec is revalidated; nodes reference earlier nodes only. */
#include "mathnb.h"
#include <string.h>
#include <stdio.h>

static int64_t rd(int64_t a, int64_t b) {
    int64_t n=a<0?-a:a, d=b<0?-b:b;
    int64_t q=n/d + (2*(n%d)>=d);
    return (a<0)!=(b<0)?-q:q;
}
static int bound(int64_t v) { return v>=-MNB_LIMIT && v<=MNB_LIMIT; }
enum { PARSE_BOUND=1, PARSE_SYNTAX=2 };
typedef struct { const char *p; mnb_spec *s; int bad; } parser;
static int failure(const parser *p) { return p->bad==PARSE_BOUND?-1:0; }
static void ws(parser *p) { while (*p->p==' ') p->p++; }
static int word(parser *p, const char *w) {
    ws(p); size_t n=strlen(w);
    if (strncmp(p->p,w,n) || (p->p[n]>='a' && p->p[n]<='z')) return 0;
    p->p+=n; return 1;
}
static int number(parser *p, int32_t *v) {
    ws(p); int digits=0, f=0, nf=0, up=0; int64_t a=0;
    while (*p->p>='0' && *p->p<='9') {
        digits++; a=a*10+(*p->p++-'0');
        if (a>10000) { p->bad=PARSE_BOUND; return 0; }
    }
    if (*p->p=='.') {
        p->p++;
        while (*p->p>='0' && *p->p<='9') {
            if (nf<4) f=f*10+(*p->p-'0');
            if (nf==4) up=*p->p>='5';
            nf++; p->p++;
        }
    }
    if (!digits && !nf) return 0;
    for (int i=nf;i<4;i++) f*=10;
    a=a*MNB_SCALE+f+up;
    if (!bound(a)) { p->bad=PARSE_BOUND; return 0; }
    *v=(int32_t)a; return 1;
}
static int signed_number(parser *p, int32_t *v) {
    ws(p); int sign=1;
    if (*p->p=='-' || *p->p=='+') sign=*p->p++=='-'?-1:1;
    if (!number(p,v)) return 0;
    *v*=sign; return 1;
}
static int node(parser *p, int op, int l, int r, int32_t v) {
    if (p->s->nodes>=MNB_NODES) { p->bad=PARSE_BOUND; return 0; }
    int i=p->s->nodes++;
    p->s->ast[i]=(mnb_node){v,(uint8_t)op,(uint8_t)l,(uint8_t)r,0};
    return i;
}
static int expression(parser *p, int prec, int depth);
static int atom(parser *p, int depth) {
    ws(p);
    if (depth>MNB_DEPTH) { p->bad=PARSE_BOUND; return 0; }
    if (p->bad) return 0;
    if (*p->p=='-' || *p->p=='+') {
        int neg=*p->p++=='-'; int a=expression(p,3,depth+1);
        return neg?node(p,MNB_NEG,a,0,0):a;
    }
    if (*p->p=='(') {
        p->p++; int a=expression(p,0,depth+1); ws(p);
        if (*p->p!=')' && !p->bad) p->bad=PARSE_SYNTAX;
        else if (*p->p==')') p->p++;
        return a;
    }
    const char *names[]={"sin","cos","sqrt","abs"};
    for (int i=0;i<4;i++) if (word(p,names[i])) {
        int a=atom(p,depth+1); return node(p,MNB_SIN+i,a,0,0);
    }
    if (word(p,"x") || word(p,"n")) return node(p,MNB_X,0,0,0);
    int32_t v;
    if (number(p,&v)) return node(p,MNB_CONST,0,0,v);
    if (!p->bad) p->bad=PARSE_SYNTAX;
    return 0;
}
static int expression(parser *p, int prec, int depth) {
    int a=atom(p,depth);
    while (!p->bad) {
        ws(p); char ch=*p->p;
        int level=ch=='+'||ch=='-'?1:ch=='*'||ch=='/'?2:ch=='^'?3:0;
        if (prec<=3 && (word(p,"squared") || word(p,"cubed"))) {
            int e=!strncmp(p->p-5,"cubed",5)?3:2;
            int b=node(p,MNB_CONST,0,0,e*MNB_SCALE); a=node(p,MNB_POW,a,b,0); continue;
        }
        if (!level || level<prec) break;
        p->p++; int b=expression(p,level+(ch!='^'),depth+1);
        int op=ch=='+'?MNB_ADD:ch=='-'?MNB_SUB:ch=='*'?MNB_MUL:ch=='/'?MNB_DIV:MNB_POW;
        a=node(p,op,a,b,0);
    }
    return a;
}
static int math_start(const char *p) {
    while (*p==' ') p++;
    if (strchr("0123456789.(-+",*p) && *p) return 1;
    parser q={p,0,0};
    return word(&q,"x") || word(&q,"n") || word(&q,"sin") || word(&q,"cos") || word(&q,"sqrt") || word(&q,"abs");
}
/* Ownership precedes limits: even oversized math-looking movie/dinner prose
 * belongs to the normal pipeline. Scan the original input, not its prefix. */
static int notebook_tokens(const char *q) {
    const char *names[]={"x","n","sin","cos","sqrt","abs","squared","cubed",
                         "from","to","with","points","for"};
    while (*q) {
        unsigned char ch=(unsigned char)*q;
        if ((ch>='a' && ch<='z') || (ch>='A' && ch<='Z')) {
            char token[8]; size_t n=0;
            do {
                if (n==sizeof token-1) return 0;
                token[n++]=(char)(ch>='A' && ch<='Z'?ch+32:ch);
                ch=(unsigned char)*++q;
            } while ((ch>='a' && ch<='z') || (ch>='A' && ch<='Z'));
            token[n]=0; int known=0;
            for (size_t i=0;i<sizeof names/sizeof *names;i++)
                if (!strcmp(token,names[i])) { known=1; break; }
            if (!known) return 0;
        } else {
            if (ch>=32 && !strchr(" 0123456789.()+-*/^,?",ch)) return 0;
            q++;
        }
    }
    return 1;
}
int mnb_parse(const char *query, mnb_spec *s) {
    char text[128]; size_t len=strlen(query);
    /* Check prefix even for overlong requests without copying unbounded data. */
    size_t n=len<127?len:127;
    for (size_t i=0;i<n;i++) text[i]=query[i]>='A'&&query[i]<='Z'?query[i]+32:query[i];
    text[n]=0;
    memset(s,0,sizeof *s); parser p={text,s,0};
    word(&p,"please");
    if (word(&p,"can you") || word(&p,"could you")) word(&p,"please");
    if (word(&p,"plot") || word(&p,"graph")) s->kind=MNB_PLOT;
    else if (word(&p,"show bars for") || word(&p,"bars for") || word(&p,"bar chart of")) s->kind=MNB_BAR;
    else if (word(&p,"table of") || word(&p,"show table of") || word(&p,"make a table of")) s->kind=MNB_TABLE;
    else return 0;
    if (!math_start(p.p)) return 0;
    if (!notebook_tokens(query+(p.p-text))) return 0;
    if (len>127) return -1;
    for (size_t i=0;i<len;i++) if ((unsigned char)text[i]<32 || (unsigned char)text[i]>126) return 0;
    s->lo=-5*MNB_SCALE; s->hi=5*MNB_SCALE; s->points=MNB_POINTS;
    if (s->kind==MNB_BAR) {
        s->points=0;
        do {
            if (s->points==MNB_BARS) return -1;
            if (!signed_number(&p,&s->bars[s->points])) return failure(&p);
            s->points++; ws(&p);
            if (*p.p!=',') break;
            p.p++;
        } while (1);
    } else {
        s->root=(uint8_t)expression(&p,0,0);
        if (p.bad) return failure(&p);
        if (s->kind==MNB_TABLE) {
            if (!(word(&p,"for n") || word(&p,"for x"))) return 0;
            word(&p,"from");
            if (!signed_number(&p,&s->lo) || !word(&p,"to") || !signed_number(&p,&s->hi)) return failure(&p);
            s->points=(uint16_t)((s->hi-s->lo)/MNB_SCALE+1);
        } else {
            if (word(&p,"from")) {
                if (!signed_number(&p,&s->lo) || !word(&p,"to") || !signed_number(&p,&s->hi)) return failure(&p);
            }
            if (word(&p,"with")) {
                int32_t count;
                if (!signed_number(&p,&count)) return failure(&p);
                if (!word(&p,"points")) return 0;
                if (count%MNB_SCALE) p.bad=PARSE_BOUND;
                s->points=(uint16_t)(count/MNB_SCALE);
            }
        }
    }
    ws(&p); if (*p.p=='?') { p.p++; ws(&p); }
    if (*p.p) return 0;
    if (p.bad || !mnb_validate(s)) return -1;
    return 1;
}
int mnb_validate(const mnb_spec *s) {
    if (s->reserved || s->kind<MNB_PLOT || s->kind>MNB_TABLE) return 0;
    if (s->kind==MNB_BAR) {
        if (!s->points || s->points>MNB_BARS || s->nodes || s->root) return 0;
        for (int i=0;i<s->points;i++) if (!bound(s->bars[i])) return 0;
        return 1;
    }
    if (!s->points || s->points>MNB_POINTS || s->lo<-100*MNB_SCALE || s->hi>100*MNB_SCALE || s->hi<s->lo) return 0;
    if (s->kind==MNB_PLOT && (s->lo==s->hi || s->points<2)) return 0;
    if (s->kind==MNB_TABLE && (s->points>16 || s->lo%MNB_SCALE || s->hi%MNB_SCALE || s->hi-s->lo!=(s->points-1)*MNB_SCALE)) return 0;
    if (!s->nodes || s->nodes>MNB_NODES || s->root!=s->nodes-1) return 0;
    uint8_t depths[MNB_NODES];
    for (int i=0;i<s->nodes;i++) {
        const mnb_node *a=&s->ast[i]; int d=1;
        if (a->op>MNB_ABS || a->reserved || !bound(a->value)) return 0;
        if (a->op>=MNB_ADD) {
            if (a->left>=i) return 0;
            d=depths[a->left]+1;
            if (a->op<=MNB_POW) {
                if (a->right>=i) return 0;
                if (d<depths[a->right]+1) d=depths[a->right]+1;
                if (a->op==MNB_POW) {
                    const mnb_node *b=&s->ast[a->right];
                    int64_t v=b->value;
                    if (b->op==MNB_NEG) v=-(int64_t)s->ast[b->left].value;
                    if ((b->op==MNB_CONST || (b->op==MNB_NEG && s->ast[b->left].op==MNB_CONST)) &&
                        (v%MNB_SCALE || v<-8*MNB_SCALE || v>8*MNB_SCALE)) return 0;
                }
            }
        }
        if (d>MNB_DEPTH) return 0;
        depths[i]=(uint8_t)d;
    }
    return 1;
}
static int32_t sine(int64_t v) {
    v%=62832;
    if (v>31416) v-=62832;
    if (v<-31416) v+=62832;
    if (v>15708) v=31416-v;
    if (v<-15708) v=-31416-v;
    int64_t term=v, sum=v;
    for (int i=1;i<=5;i++) {
        term=-rd(term*v*v,(int64_t)MNB_SCALE*MNB_SCALE*(2*i)*(2*i+1)); sum+=term;
    }
    return (int32_t)sum;
}
static int32_t square_root(int32_t a) {
    int64_t v=(int64_t)a*MNB_SCALE, lo=0, hi=1000001;
    while (lo+1<hi) { int64_t m=(lo+hi)/2; if (m*m<=v) lo=m; else hi=m; }
    return (int32_t)(lo+(v-lo*lo>=hi*hi-v));
}
int mnb_evaluate(const mnb_spec *s, mnb_values *out) {
    if (!mnb_validate(s)) return 0;
    for (int k=0;k<s->points;k++) {
        int32_t x=s->kind==MNB_BAR?(k+1)*MNB_SCALE:s->points==1?s->lo:
            s->lo+(int32_t)rd((int64_t)(s->hi-s->lo)*k,s->points-1);
        int64_t vals[MNB_NODES]={0};
        for (int i=0;i<s->nodes;i++) {
            const mnb_node *n=&s->ast[i]; int64_t a=n->op>=MNB_ADD?vals[n->left]:0;
            int64_t b=n->op>=MNB_ADD&&n->op<=MNB_POW?vals[n->right]:0, v=0;
            switch (n->op) {
            case MNB_CONST: v=n->value; break;
            case MNB_X: v=x; break;
            case MNB_ADD: v=a+b; break;
            case MNB_SUB: v=a-b; break;
            case MNB_MUL: v=rd(a*b,MNB_SCALE); break;
            case MNB_DIV: if (!b) return 0; v=rd(a*MNB_SCALE,b); break;
            case MNB_NEG: v=-a; break;
            case MNB_ABS: v=a<0?-a:a; break;
            case MNB_SIN: v=sine(a); break;
            case MNB_COS: v=sine(a+15708); break;
            case MNB_SQRT: if (a<0) return 0; v=square_root((int32_t)a); break;
            case MNB_POW: {
                if (b%MNB_SCALE || b<-8*MNB_SCALE || b>8*MNB_SCALE) return 0;
                int e=(int)(b/MNB_SCALE); v=MNB_SCALE;
                for (int j=0;j<(e<0?-e:e);j++) { v=rd(v*a,MNB_SCALE); if (!bound(v)) return 0; }
                if (e<0) { if (!v) return 0; v=rd((int64_t)MNB_SCALE*MNB_SCALE,v); }
                break;
            }
            default: return 0;
            }
            if (!bound(v)) return 0;
            vals[i]=v;
        }
        out->x[k]=x; out->y[k]=s->kind==MNB_BAR?s->bars[k]:(int32_t)vals[s->root];
    }
    return 1;
}
