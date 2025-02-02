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
    """Assemble the required bytes to jump to some address."""
    instructions = []
    instructions.append(Instruction.create_branch(Code.JMP_REL32_64, target))
    encoder = BlockEncoder(64)
    encoder.add_many(instructions)
    return encoder.encode(rip)


def load_rsp(rsp_buff_addr: int, rip: int) -> bytes:
    """Assemble the required bytes to write the value of the rsp register into a buffer which can be accessed
    by the detour.
    The asm which is assembled is
    ```x86asm
    mov rax, [rsp]
    mov [rsp_buff_addr], rax
    ```
    """
    instructions = [
        Instruction.create_reg_mem(
            Code.MOV_R64_RM64,
            Register.RAX,
            MemoryOperand(Register.RSP),
        ),
        Instruction.create_mem_reg(
            Code.MOV_MOFFS64_RAX,
            MemoryOperand(displ=rsp_buff_addr, displ_size=8),
            Register.RAX,
        ),
    ]
    encoder = BlockEncoder(64)
    encoder.add_many(instructions)
    return encoder.encode(rip)


def get_first_jmp_addr(data: bytes, ip: int) -> int:
    """Get the address of the first jmp instruction found in the bytes when disassembled."""
    decoder = Decoder(BITS, data, ip=ip)
    for instr in decoder:
        if instr.mnemonic == Mnemonic.JMP:
            return instr.near_branch_target
    return 0


def disassemble(data: bytes, ip: int) -> None:
    """Utility function for disassembly bytes."""
    formatter = FastFormatter()
    decoder = Decoder(BITS, data, ip=ip)
    for instruction in decoder:
        disasm = formatter.format(instruction)
        logger.info(f"{instruction.ip:016X} {disasm}")
    logger.info("")
