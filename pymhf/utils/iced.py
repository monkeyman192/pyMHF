# A few functions to interface with iced_x86.

import logging
import struct

try:
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

    HAS_ICED = True
except ImportError:
    HAS_ICED = False

logger = logging.getLogger("iced")


BITS = struct.calcsize("P") * 8


def create_jmp_bytes(target: int, rip: int):
    """Assemble the required bytes to jump to some address."""
    instructions = []
    instructions.append(Instruction.create_branch(Code.JMP_REL32_64, target))
    encoder = BlockEncoder(64)
    encoder.add_many(instructions)
    return encoder.encode(rip)


def generate_load_stack_pointer_bytes(buff_addr: int, rip: int, bits: int = 64) -> bytes:
    if bits == 64:
        return load_rsp(buff_addr, rip)
    elif bits == 32:
        return load_esp(buff_addr, rip)
    else:
        raise ValueError("Number of bits must be 32 or 64")


def load_rsp(buff_addr: int, rip: int) -> bytes:
    """Assemble the required bytes to write the value of the rsp register into a buffer which can be accessed
    by the detour. This is for getting the caller address in a 64 bit process.
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
            MemoryOperand(displ=buff_addr, displ_size=8),
            Register.RAX,
        ),
    ]
    encoder = BlockEncoder(64)
    encoder.add_many(instructions)
    return encoder.encode(rip)


def load_esp(buff_addr: int, rip: int) -> bytes:
    """Assemble the required bytes to write the value of the esp register into a buffer which can be accessed
    by the detour. This is for getting the caller address in a 32 bit process.
    The asm which is assembled is
    ```x86asm
    mov eax, [esp]
    mov [rsp_buff_addr], eax
    ```
    """
    instructions = [
        Instruction.create_reg_mem(
            Code.MOV_R32_RM32,
            Register.EAX,
            MemoryOperand(Register.ESP),
        ),
        Instruction.create_mem_reg(
            Code.MOV_MOFFS32_EAX,
            MemoryOperand(displ=buff_addr, displ_size=4),
            Register.EAX,
        ),
    ]
    encoder = BlockEncoder(32)
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
