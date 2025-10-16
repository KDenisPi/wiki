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
#include <pthread.h>
#include <sched.h>
#include <algorithm>

#include "defines.h"
#include "item_reader.h"
#include "item_parser.h"
#include "prop_dict.h"
#include "receiver_impl.h"

namespace wiki {

class WiKi{
public:
    /**
     * @brief Construct a new WiKi object
     *
     */
    WiKi() {
        props = std::make_shared<Properties>();

        for(int i = 0; i < max_threads; i++){
            buffers[i] = std::shared_ptr<char>(new char[max_buffer_size]);
            threads_vars[i] = 0;
        }

        load_important_properties();
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
    const static unsigned int max_threads = MAX_PARSING_THREADS; //5;

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
        auto hw_concurrency = std::thread::hardware_concurrency();
        std::cout << "HW Concurrency : " << hw_concurrency << std::endl;
        const auto assign_threads = (use_concurrency && (hw_concurrency > max_threads));

        for(int i = 0; i < max_threads; i++){
            parsers[i] = std::make_shared<ItemParser>(i, &threads_vars[i], buffers[i], props);
            threads[i] = std::thread(&ItemParser::worker, parsers[i].get());
            if(assign_threads){
                setThreadAffinity(threads[i], i);
            }
            threads[i].detach();
        }

        th_main = std::thread(&WiKi::worker, this);
        if(assign_threads){
            setThreadAffinity(th_main, max_threads);
        }
        th_main.join();
    }

    /**
     * @brief Set the Thread Affinity object
     *
     * @param th
     * @param core_id
     * @return true
     * @return false
     */
    bool setThreadAffinity(std::thread& th, int core_id){
        cpu_set_t cpuset;
        CPU_ZERO(&cpuset);           // Clear the CPU set
        CPU_SET(core_id, &cpuset);   // Add the desired core to the set

        // Get the native pthread handle from the std::thread object
        pthread_t handle = th.native_handle();

        // Set the CPU affinity
        int result = pthread_setaffinity_np(handle, sizeof(cpu_set_t), &cpuset);
        if (result != 0) {
            std::cerr << "Error setting thread affinity: " << result << std::endl;
            return false;
        }

        std::cout << "Thread affinity " << handle << " set to core " << core_id << std::endl;
        return true;
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
        const bool res =  props->load(filename);
        return res;
    }

    void load_important_properties(){
/*
        std::vector<pID> v_props = {"P31", "P50", "P101", "P136", "P921", "P425", "P569",\
                "P570", "P571", "P577", "P585", "P793", "P921", "P1191", "P2093", "P3150", "P3989", "P4647"\
            "P4647", "P9899", "P10673"};
*/
        std::vector<pID> v_props = {"P31"};

        props->load_important_property(v_props);
    }

private:
    std::mutex cv_m;
    std::thread th_main;

    bool finish = false;
    bool use_concurrency = true;    //Try to assign working thread to the separate cores if it is possible

    std::shared_ptr<ItemParser> parsers[max_threads];
    std::shared_ptr<Properties> props;

    std::shared_ptr<ReceiverImpl> receiver;

    ItemReader reader;

};

}//namespace

#endif