/* SPDX-License-Identifier: MIT
 * ARMv5TE: packed int16 activations, serialized int8 weights. No SMLAD.
 * Private leaf: x must be word aligned; w may have any byte alignment.
 * Clobbers only caller-saved r0,r2,r3,r12,lr. BX preserves interworking.
 */
.syntax unified
.arch armv5te
.arm
.section .itcm,"ax",%progbits
.align 2
.global cds_dot32_arm
.type cds_dot32_arm,%function
cds_dot32_arm:
    push {lr}
    mov r2, #0
    .set off, 0
    .rept 16
        ldr r12, [r1, #off*2]
        ldrsb r3, [r0, #off]
        ldrsb lr, [r0, #off+1]
        smlabb r2, r3, r12, r2
        smlabt r2, lr, r12, r2
        .set off, off+2
    .endr
    mov r0, r2
    pop {lr}
    bx lr
.size cds_dot32_arm, .-cds_dot32_arm
.section .note.GNU-stack,"",%progbits
