# A few functions to interface with iced_x86.

import logging

from iced_x86 import (
    BlockEncoder,
    Code,
    Decoder,
    FastFormatter,
    Instruction,
    MemoryOperand,
    Mnemonic,
    Register,
)

logger = logging.getLogger("iced")


BITS = 64


def create_jmp_bytes(target: int, rip: int):
    instructions = []
    instructions.append(Instruction.create_branch(Code.JMP_REL32_64, target))

    encoder = BlockEncoder(64)
    encoder.add_many(instructions)
    return encoder.encode(rip)


def load_rsp(pAllocated: int, rip: int):
    instructions = [
        Instruction.create_reg_mem(
            Code.MOV_R64_RM64,
            Register.RAX,
            MemoryOperand(Register.RSP),
        ),
        Instruction.create_mem_reg(
            Code.MOV_MOFFS64_RAX,
            MemoryOperand(displ=pAllocated, displ_size=8),
            Register.RAX,
        ),
    ]
    encoder = BlockEncoder(64)
    encoder.add_many(instructions)
    return encoder.encode(rip)


def get_first_jmp_addr(data: bytes, ip: int) -> int:
    decoder = Decoder(BITS, data, ip=ip)
    for instr in decoder:
        if instr.mnemonic == Mnemonic.JMP:
            return instr.near_branch_target
    return 0


def disassemble(data: bytes, ip: int) -> None:
    formatter = FastFormatter()
    decoder = Decoder(BITS, data, ip=ip)
    for instruction in decoder:
        disasm = formatter.format(instruction)
        logger.info(f"{instruction.ip:016X} {disasm}")
    logger.info("")
