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
#include "prop_dict.h"

namespace wiki {

class WiKi{
public:
    /**
     * @brief Construct a new WiKi object
     *
     */
    WiKi() {
        for(int i = 0; i < max_threads; i++){
            buffers[i] = std::shared_ptr<char>(new char[max_buffer_size]);
            threads_vars[i] = 0;
        }
    }

    /**
     * @brief Destroy the WiKi object
     *
     */
    virtual ~WiKi() {}

    /**
     * @brief Max number of parser threads
     *
     */
    const static int max_threads = MAX_PARSING_THREADS; //5;

    /**
     * @brief Maximum size of Wiki Item
     *
     */
    const static size_t max_buffer_size = MAX_LINE_LENGTH;

    /**
     * @brief Parser thread synchronization
     *
     */
    std::atomic_int threads_vars[max_threads];

    /**
     * @brief Read buffers
     *
     */
    std::shared_ptr<char> buffers[max_threads];

    /**
     * @brief Threads pool
     *
     */
    std::thread threads[max_threads];

    /**
     * @brief
     *
     */
    void worker();


    /**
     * @brief
     *
     * @return * void
     */
    void start(){
        for(int i = 0; i < max_threads; i++){
            parsers[i] = std::make_shared<ItemParser>(i, &threads_vars[i], buffers[i]);
            threads[i] = std::thread(&ItemParser::worker, parsers[i].get());
            threads[i].detach();
        }

        th_main = std::thread(&WiKi::worker, this);
        th_main.join();
    }

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    const bool is_finish() const{
        return finish;
    }

    /**
     * @brief Set the finish object
     *
     */
    void set_finish(){
        //const std::lock_guard<std::mutex> lock(cv_m);
        finish = true;
    }

    /**
     * @brief Initialize reader object
     *
     * @param filename
     * @return true
     * @return false
     */
    bool load_source(const std::string& filename){
        return reader.init(filename);
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    bool load_properties(const std::string& filename){
        const bool res =  props.load(filename);
        if(rand){
            std::vector<pID> v_props = {"P31", "P50", "P101", "P136", "P921", "P425", "P569",\
                 "P570", "P577", "P921", "P1191", "P2093", "P3150", "P3989", "P4647"\
                "P4647", "P9899", "P10673"};

            props.load_important_property(v_props);
        }
        return res;
    }

private:
    std::mutex cv_m;
    std::thread th_main;

    bool finish = false;

    std::shared_ptr<ItemParser> parsers[max_threads];
    ItemReader reader;
    Properties props;

};

}//namespace

#endif