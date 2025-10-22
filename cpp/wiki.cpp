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
#include "smallthings.h"

namespace wiki {

/**
 * @brief
 *
 */
void WiKi::worker(){
    unsigned long counter = 0;
    std::cout << piutils::get_time_string(false) << " Main worker has started" << std::endl;

    if(!reader.is_ready()){
        std::cout << "Data reader is not ready" << std::endl;
    }
    else{
        auto fn_all_done = [&]() {
            int count = 0;
            for(int i = 0; i < this->max_threads; i++){
                count += this->threads_vars[i].load();
            }
            return (this->is_finish() || (count == 0));
        };

        ItemReader::Res read_res = ItemReader::Res::OK;
        for(;;){

            for(int i = 0; i < this->max_threads; i++){
                read_res = this->reader.next(static_cast<char*>(buffers[i].get()), max_buffer_size);
                if(ItemReader::Res::OK != read_res){
                    break;
                }
                this->threads_vars[i].fetch_add(1);
                counter++;
            }

            while(!fn_all_done());

            if(ItemReader::Res::OK != read_res){
                std::cout << (ItemReader::Res::END_OF_FILE == read_res ? "End of file detected" : "Reading error detected") << std::endl;
                break;
            }

            if( is_finish() ){
                std::cout << " Finish signal detected" << std::endl;
                break;
            }

            /*
            if(((counter/max_threads) % 1000) == 0){
                std::cout << "Items processed: " << std::to_string(counter) << " " << std::to_string(counter/max_threads) << " " << get_flush_bulk() <<  std::endl;
            }
            */

            //flush data
            if( get_flush_bulk() > 0 && ((counter/max_threads) % get_flush_bulk()) == 0){
                receiver->flush();
                std::cout << piutils::get_time_string(false) << " Items processed: " << std::to_string(counter) << " Per thread: " << std::to_string(counter/max_threads) << std::endl;
            }

            //end bulk processing
            if( (counter/max_threads) >= get_bulk_size() ){
                break;
            }
        }

        //save current position in source file
        save_position_file();

    }


    //send finish signal to working threads
    for(int i = 0; i < this->max_threads; i++){
        parsers[i]->set_finish();
    }

    for(int i = 0; i < this->max_threads; i++){
        if(threads[i].joinable()){
            std::cout << "Join to : " << i ;
            threads[i].join();
            std::cout << " Thread finished : " << i << std::endl;
        }
    }

    std::cout << piutils::get_time_string(false) << " Main worker finished" << std::endl;
}

}