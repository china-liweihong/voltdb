/* This file is part of VoltDB.
 * Copyright (C) 2008-2017 VoltDB Inc.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with VoltDB.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef VOLTDB_LARGETEMPTABLEBLOCK_HPP
#define VOLTDB_LARGETEMPTABLEBLOCK_HPP

#include <iterator>
#include <memory>
#include <utility>

#include "boost/foreach.hpp"
#include "boost/mpl/if.hpp"
#include "boost/range.hpp"

#include "common/tabletuple.h"

namespace voltdb {

class TableTuple;
class TupleSchema;

/**
 * A wrapper around a buffer of memory used to store tuples.
 *
 * The lower-addressed memory of the buffer is used to store tuples of
 * fixed size, which is similar to how persistent table blocks store
 * tuples.  The higher-addressed memory stores non-inlined,
 * variable-length objects referenced in the tuples.
 *
 * As tuples are inserted into the block, both tuple and non-inlined
 * memory grow towards the middle of the buffer.  The buffer is full
 * when there is not enough room in the middle of the buffer for the
 * next tuple.
 *
 * This block layout is chosen so that the whole block may be written
 * to disk as a self-contained unit, and reloaded later (since block
 * may be at a different memory address, pointers to non-inlined data in
 * the tuples will need to be updated).
 */
class LargeTempTableBlock {
public:

    template<bool IsConst>
    class LttBlockIterator;

    typedef LttBlockIterator<false> iterator;
    typedef LttBlockIterator<true> const_iterator;

    /** The size of all large temp table blocks.  Some notes about
        block size:
        - The maximum row size is 2MB.
        - A small block size will waste space if tuples large
        - A large block size will waste space if tables and tuples are
          small
        8MB seems like a reasonable choice since it's large enough to
        hold a few tuples of the maximum size.
    */
    static const size_t BLOCK_SIZE_IN_BYTES = 8 * 1024 * 1024; // 8 MB

    /** constructor for a new block. */
    LargeTempTableBlock(int64_t id, TupleSchema* schema);

    /** Return the unique ID for this block */
    int64_t id() const {
        return m_id;
    }

    /** insert a tuple into this block.  Returns true if insertion was
        successful.  */
    bool insertTuple(const TableTuple& source);

    /** insert a tuple into this block, assuming that any non-inlined
        data is already present in this block at an offset of
        (<non-inlined object address> - origAddress). Returns true if
        insertion was successful.  */
    bool insertTupleRelocateNonInlinedFields(const TableTuple& source, const char* origAddress);

    /** Because we can allocate non-inlined objects into LTT blocks,
        this class needs to function like a pool, and this allocate
        method provides this. */
    void* allocate(std::size_t size);

    /** Return the ordinal position of the next free slot in this
        block. */
    uint32_t unusedTupleBoundary() {
        return m_activeTupleCount;
    }

    /** Return a pointer to the storage for this block. */
    char* address() {
        return m_storage.get();
    }

    /** Returns the amount of memory used by this block.  For blocks
        that are resident (not stored to disk) this will return
        BLOCK_SIZE_IN_BYTES, and zero otherwise.
        Note that this value may not be equal to
        getAllocatedTupleMemory() + getAllocatedPoolMemory() because
        of unused space at the middle of the block. */
    int64_t getAllocatedMemory() const;

    /** Return the number of bytes used to store tuples in this
        block */
    int64_t getAllocatedTupleMemory() const;

    /** Return the number of bytes used to store non-inlined objects in
        this block. */
    int64_t getAllocatedPoolMemory() const;

    /** Release the storage associated with this block (so it can be
        persisted to disk).  Marks the block as "stored." */
    std::unique_ptr<char[]> releaseData();

    /** Set the storage associated with this block (as when loading
        from disk) */
    void setData(char* origAddress, std::unique_ptr<char[]> storage);

    /** Copy the non-inlined data segment from the given block into
        this one. */
    void copyNonInlinedData(const LargeTempTableBlock& srcBlock);

    /** Returns true if this block is pinned in the cache and may not
        be stored to disk (i.e., we are currently inserting tuples
        into or iterating over the tuples in this block)  */
    bool isPinned() const {
        return m_isPinned;
    }

    /** Mark this block as pinned and un-evictable */
    void pin() {
        assert(!m_isPinned);
        m_isPinned = true;
    }

    /** Mark this block as unpinned and evictable */
    void unpin() {
        assert(m_isPinned);
        m_isPinned = false;
    }

    /** Returns true if this block is currently loaded into memory */
    bool isResident() const {
        return m_storage.get() != NULL;
    }

    /** Returns true if this block is stored on disk.  (May or may not
        also be resident) */
    bool isStored() const {
        return m_isStored;
    }

    /** Return the number of tuples in this block */
    int64_t activeTupleCount() const {
        return m_activeTupleCount;
    }

    /** Return the schema of the tuples in this block */
    const TupleSchema* schema() const {
        return m_schema;
    }

    /** Return the schema of the tuples in this block (non-const version) */
    TupleSchema* schema() {
        return m_schema;
    }

    /** Clear all the data out of this block. */
    void clearForTest() {
        m_tupleInsertionPoint = m_storage.get();
        m_nonInlinedInsertionPoint = m_storage.get() + BLOCK_SIZE_IN_BYTES;
        m_activeTupleCount = 0;
    }

    LargeTempTableBlock::iterator begin();
    LargeTempTableBlock::const_iterator begin() const;
    LargeTempTableBlock::const_iterator cbegin() const;

    LargeTempTableBlock::iterator end();
    LargeTempTableBlock::const_iterator end() const;
    LargeTempTableBlock::const_iterator cend() const;

    /** This debug method will skip printing non-inlined strings (will
        just print their address) to avoid a SEGV when debugging. */
    std::string debug() const;

    /** This debug method will print non-inlined strings, which could
        cause a crash if the StringRef pointer is invalid. */
    std::string debugUnsafe() const;

    struct Tuple {

        TableTuple toTableTuple(const TupleSchema* schema) {
            return TableTuple(reinterpret_cast<char*>(this), schema);
        }

        const TableTuple toTableTuple(const TupleSchema* schema) const {
            return TableTuple(reinterpret_cast<char*>(const_cast<Tuple*>(this)), schema);
        }

        Tuple(const Tuple&) = delete;
        Tuple& operator=(const Tuple&) = delete;

        char m_statusByte;
        char m_tupleData[];
    };

 private:

    /** Update all fields referencing non-inlined data, assuming they
        were relative to the given address. */
    void relocateNonInlinedFields(char* origAddress);

    /** the ID of this block */
    int64_t m_id;

    /** the schema for the data (owned by the table) */
    TupleSchema * m_schema;

    /** Pointer to block storage */
    std::unique_ptr<char[]> m_storage;

    /** Points the address where the next tuple will be inserted */
    char* m_tupleInsertionPoint;

    /** Points to the byte after the end of the storage buffer (before
        any non-inlined data has been inserted), or to the first byte
        of the last non-inlined object that was inserted.
        I.e., m_nonInlinedInsertionPoint - [next non-inlined object size]
        is where the next non-inlined object will be inserted. */
    char* m_nonInlinedInsertionPoint;

    /** True if this object cannot be evicted from the LTT block cache
        and stored to disk */
    bool m_isPinned;

    /** True if this block is stored on disk (may or may not be currently resident).
        Blocks that are resident and also stored can be evicted without doing any I/O. */
    bool m_isStored;

    /** Number of tuples currently in this block */
    int64_t m_activeTupleCount;
};

template<bool IsConst>
class LargeTempTableBlock::LttBlockIterator {
public:

    friend class LargeTempTableBlock::LttBlockIterator<true>;
    typedef std::random_access_iterator_tag iterator_category;
    typedef LargeTempTableBlock::Tuple value_type;
    typedef std::ptrdiff_t difference_type;
    typedef typename boost::mpl::if_c<IsConst, const value_type&, value_type&>::type reference;
    typedef typename boost::mpl::if_c<IsConst, const value_type*, value_type*>::type pointer;

    LttBlockIterator()
        : m_tupleLength(0)
        , m_tupleAddress(NULL)
    {
    }

     LttBlockIterator(const TupleSchema* schema, char* storage)
        : m_tupleLength(schema->tupleLength() + TUPLE_HEADER_SIZE)
        , m_tupleAddress(storage)
    {
    }

     LttBlockIterator(int tupleLength, char* storage)
         : m_tupleLength(tupleLength)
         , m_tupleAddress(storage)
    {
    }

    // You can convert a regular iterator to a const_iterator
    operator LttBlockIterator<true>() const {
        return LttBlockIterator<true>(m_tupleLength, m_tupleAddress);
    }

    bool operator==(const LttBlockIterator& that) const {
        return m_tupleAddress == that.m_tupleAddress;
    }

    bool operator!=(const LttBlockIterator& that) const {
        return m_tupleAddress != that.m_tupleAddress;
    }

    reference operator*() {
        LttBlockIterator::pointer tuple = reinterpret_cast<pointer>(m_tupleAddress);
        return *tuple;
    }

    pointer operator->() {
        LttBlockIterator::pointer tuple = reinterpret_cast<pointer>(m_tupleAddress);
        return tuple;
    }

    // pre-increment
    LttBlockIterator& operator++() {
        m_tupleAddress += m_tupleLength;
        return *this;
    }

    // post-increment
    LttBlockIterator operator++(int) {
        LttBlockIterator orig = *this;
        ++(*this);
        return orig;
    }

    // pre-decrement
    LttBlockIterator& operator--() {
        m_tupleAddress -= m_tupleLength;
        return *this;
    }

    // post-decrement
    LttBlockIterator operator--(int) {
        LttBlockIterator orig = *this;
        --(*this);
        return orig;
    }

    LttBlockIterator& operator+=(difference_type n) {
        m_tupleAddress += (n * m_tupleLength);
        return *this;
    }

    LttBlockIterator& operator-=(difference_type n) {
        m_tupleAddress -= (n * m_tupleLength);
        return *this;
    }

    LttBlockIterator operator+(difference_type n) {
        LttBlockIterator it{*this};
        it += n;
        return it;
    }

    LttBlockIterator operator-(difference_type n) {
        LttBlockIterator it{*this};
        it -= n;
        return it;
    }

    difference_type operator-(const LttBlockIterator& that) {
        std::ptrdiff_t ptrdiff = m_tupleAddress - that.m_tupleAddress;
        return ptrdiff / m_tupleLength;
    }

    reference operator[](difference_type n) {
        LttBlockIterator temp{*this + n};
        return *temp;
    }

    // relational operators
    bool operator>(const LttBlockIterator& that) {
        return m_tupleAddress > that.m_tupleAddress;
    }

    bool operator<(const LttBlockIterator& that) {
        return m_tupleAddress < that.m_tupleAddress;
    }

    bool operator>=(const LttBlockIterator& that) {
        return m_tupleAddress >= that.m_tupleAddress;
    }

    bool operator<=(const LttBlockIterator& that) {
        return m_tupleAddress <= that.m_tupleAddress;
    }

private:

    int m_tupleLength;
    char * m_tupleAddress;
};

template<bool IsConst>
inline LargeTempTableBlock::LttBlockIterator<IsConst> operator+(typename LargeTempTableBlock::LttBlockIterator<IsConst>::difference_type n,
                                                                LargeTempTableBlock::LttBlockIterator<IsConst> it) {
    return it + n;
}

} // end namespace voltdb

// Make LargeTempTableBlock::iterator work with BOOST_FOREACH
namespace boost {

template<>
struct range_mutable_iterator<voltdb::LargeTempTableBlock> {
    typedef voltdb::LargeTempTableBlock::iterator type;
};

template<>
struct range_const_iterator<voltdb::LargeTempTableBlock> {
    typedef voltdb::LargeTempTableBlock::const_iterator type;
};

} // end namespace boost


#endif // VOLTDB_LARGETEMPTABLEBLOCK_HPP
