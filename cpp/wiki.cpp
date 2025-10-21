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

    auto fn_all_done = [&]() {
        int count = 0;
        for(int i = 0; i < this->max_threads; i++){
            count += this->threads_vars[i].load();
        }
        return (this->is_finish() || (count == 0));
    };

    int counter = 0;
    bool last_read_success = true;
    for(;;){

        for(int i = 0; i < this->max_threads; i++){
            last_read_success = this->reader.next(static_cast<char*>(buffers[i].get()), max_buffer_size);
            if(!last_read_success){
                std::cout << "Read error" << std::endl;
                break;
            }
            this->threads_vars[i].fetch_add(1);
            counter++;
        }

        while(!fn_all_done());

        if(!last_read_success && fn_all_done()){
            std::cout << "Read error: " << last_read_success << " and nothing to do:" << fn_all_done() << std::endl;
            break;
        }

        if(!last_read_success || is_finish()){
            std::cout << "Read error: " << last_read_success << " Is finish: " << is_finish() << std::endl;
            break;
        }
    }

    std::cout << "Counter: " << std::to_string(counter) << std::endl;
    std::cout << "File: " << reader.get_filename() << " Position: " << reader.get_pos() << std::endl;

    save_position_file();

    for(int i = 0; i < this->max_threads; i++){
        parsers[i]->set_finish();
    }
    std::cout << "Wait for child threads" << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(2));

    for(int i = 0; i < this->max_threads; i++){
        if(threads[i].joinable()){
            std::cout << "Join to : " << i << std::endl;
            threads[i].join();
            std::cout << "Thread finished : " << i << std::endl;
        }
    }

    std::cout << "Main worker finished" << std::endl;
}

}