/**
 * @file wiki.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-09-12
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <chrono>
#include "wiki.h"

namespace wiki {

/**
 * @brief
 *
 */
void WiKi::worker(){

    if(!reader.is_ready()){
        std::cout << "Data reader is not ready" << std::endl;
        return;
    }

    //std::this_thread::sleep_for(std::chrono::seconds(3));
    //std::cout << "Main worker finished" << std::endl;
    //return;

    auto fn_all_done = [&]() {
        int count = 0;
        for(int i = 0; i < this->max_threads; i++){
            count += this->threads_vars[i].load();
            std::cout << "Fn. Index: " << i << " Value: " << this->threads_vars[i].load() << std::endl;
        }
        return (this->is_finish() || (count == 0));
    };

    bool last_read_success = true;
    std::unique_lock<std::mutex> lk(this->cv_m);

    for(;;){

        for(int i = 0; i < this->max_threads; i++){
            last_read_success = this->reader.next(static_cast<char*>(buffers[i].get()), max_buffer_size);
            if(!last_read_success){
                std::cout << "Read error" << std::endl;
                break;
            }
            this->threads_vars[i].fetch_add(1);
        }

        //std::this_thread::sleep_for(std::chrono::milliseconds(10));
        for(int i = 0; i < this->max_threads; i++){
            std::cout << "Main. Index: " << i << " Value: " << this->threads_vars[i].load() << std::endl;
        }

/*
        if(!last_read_success && fn_all_done()){
            std::cout << "Read error and nothing to do" << std::endl;
            break;
        }
*/
        this->cv.wait(lk, fn_all_done);

        break;

        if(!last_read_success || is_finish())
            break;
    }

    std::cout << "Main worker finished" << std::endl;
}

}