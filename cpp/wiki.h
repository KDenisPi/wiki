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
#include "item_parser.h"

namespace wiki {

class WiKi{
public:
    WiKi() {
        for(int i = 0; i < max_threads; i++){
            buffers[i] = std::shared_ptr<char>(new char[max_buffer_size]);
        }
    }

    /**
     * @brief Destroy the Wi Ki object
     *
     */
    virtual ~WiKi() {}

    /**
     * @brief Max number of parser threads
     *
     */
    const static int max_threads = 5; //5;

    const static size_t max_buffer_size = 1024*1024*5;

    /**
     * @brief Parser theread synchronization
     *
     */
    std::atomic_int threads_vars[max_threads] = {0,0};

    /**
     * @brief Read buffers
     *
     */
    std::shared_ptr<char> buffers[max_threads];

    std::thread threads[max_threads];

    /**
     * @brief
     *
     */
    void worker();


    void start(){
        for(int i = 0; i < max_threads; i++){
            parsers[i] = std::make_shared<ItemParser>(i, &threads_vars[i], buffers[i]);
            threads[i] = std::thread(&ItemParser::worker, parsers[i].get());
            threads[i].detach();
        }

        th_main = std::thread(&WiKi::worker, this);
        th_main.join();
    }

    const bool is_finish() const{
        return finish;
    }

    void set_finish(){
        std::unique_lock<std::mutex> lk(cv_m);
        finish = true;
    }

    bool load_source(const std::string& filename){
        return reader.init(filename);
    }

private:
    std::condition_variable cv;
    std::mutex cv_m;

    std::thread th_main;

    bool finish = false;

    std::shared_ptr<ItemParser> parsers[max_threads];
    ItemReader reader;

};

}//namespace

#endif