/**
 * @file wiki.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-09-12
 *
 * @copyright Copyright (c) 2025
 *
 */
#ifndef WIKI_WIKI
#define WIKI_WIKI

#include <atomic>
#include <condition_variable>
#include <thread>
#include <mutex>

#include "defines.h"
#include "item_reader.h"

namespace wiki {

class WiKi{
public:
    WiKi() {}
    virtual ~WiKi() {}

    /**
     * @brief Max number of parser threads
     *
     */
    const static int max_threads = 5;

    const static size_t max_buffer_size = MAX_LINE_LENGTH;

    /**
     * @brief Parser theread synchronization
     *
     */
    static std::atomic_int threads[];

    /**
     * @brief Read buffers
     *
     */
    char buffers[max_threads][MAX_LINE_LENGTH];

    void worker();

private:
    std::condition_variable cv;
    std::mutex cv_m;

    ItemReader reader;

};

}//namespace

#endif