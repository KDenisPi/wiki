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

#include "wiki.h"

namespace wiki {

std::atomic_int WiKi::threads[WiKi::max_threads] = {0,0,0,0,0};

/**
 * @brief
 *
 */
void WiKi::worker(){

    if(!reader.is_ready()){
        return;
    }

    auto fn_all_done = [&]() {
        int count = 0;
        for(int i = 0; i < this->max_threads; i++){
            count += this->threads[i].load();
        }
        return (count == 0);
    };

    bool last_read_success = true;

    for(;;){

        for(int i = 0; i < this->max_threads; i++){
            last_read_success = this->reader.next(static_cast<char*>(&buffers[i][0]), max_buffer_size);
            if(!last_read_success)
                break;

            this->threads->fetch_add(1);
        }

        {
            std::unique_lock<std::mutex> lk(this->cv_m);
            this->cv.wait(lk, fn_all_done);
        }

        if(!last_read_success)
            break;
    }

}

}