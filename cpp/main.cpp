/**
 * @file main.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-07
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <memory>

//#include "prop_dict.h"
#include "wiki.h"
#include "smallthings.h"

using namespace std;

int main (int argc, char* argv[])
{
    std::cout << piutils::get_time_string(false) << " started" << std::endl;

    if(argc < 2){
        std::cout << "Missing parameters." << "wpars data.json [properties.json position_file] " << std::endl;
        exit(EXIT_FAILURE);
    }

    wiki::WiKi wk;

    wk.set_bulk_size(5000000); //5M * MAX_PARSING_THREADS = 30M
    wk.set_flush_bulk(50000); //100K * MAX_PARSING_THREADS = 600K

    wk.set_save_pos_every(100000);
    wk.set_debug_print(false);

    if(argc >= 3){
        wk.load_properties(argv[2]);
    }

    if(argc >= 4){
        wk.load_position_file(argv[3]);
    }

    if(!wk.load_source(std::string(argv[1]))){
        std::cout << "Could not load source file" << std::string(argv[1]) << std::endl;
        exit(EXIT_FAILURE);
    }

    //wait untill main thread will finish (TODO: Add signal processor)
    wk.start();

    std::cout << piutils::get_time_string(false) << " finished" << std::endl;
    exit(EXIT_SUCCESS);
}
