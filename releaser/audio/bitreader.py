"""Minimaler MSB-first-Bitleser fuer Bitstream-Header.

Wird vom EC-3-Parser gebraucht, weil dessen BSI-Header nicht byte-, sondern
bitausgerichtet ist und viele Felder bedingt vorkommen.
"""

from __future__ import annotations


class BitReaderError(Exception):
    pass


class BitReader:
    __slots__ = ("_data", "_pos", "_limit")

    def __init__(self, data: bytes, bit_offset: int = 0):
        self._data = data
        self._pos = bit_offset
        self._limit = len(data) * 8

    @property
    def pos(self) -> int:
        return self._pos

    @property
    def remaining(self) -> int:
        return self._limit - self._pos

    def read(self, n: int) -> int:
        if n < 0:
            raise BitReaderError("negative Bitanzahl")
        if self._pos + n > self._limit:
            raise BitReaderError(
                f"Bitstream zu kurz: {n} Bits ab Position {self._pos}, "
                f"nur {self.remaining} verfuegbar"
            )
        value = 0
        pos = self._pos
        for _ in range(n):
            byte = self._data[pos >> 3]
            bit = (byte >> (7 - (pos & 7))) & 1
            value = (value << 1) | bit
            pos += 1
        self._pos = pos
        return value

    def bit(self) -> int:
        return self.read(1)

    def flag(self) -> bool:
        return bool(self.read(1))

    def skip(self, n: int) -> None:
        if self._pos + n > self._limit:
            raise BitReaderError("Bitstream zu kurz zum Ueberspringen")
        self._pos += n

    def align(self) -> None:
        if self._pos & 7:
            self._pos = (self._pos + 7) & ~7
