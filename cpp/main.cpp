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

using namespace std;

int main (int argc, char* argv[])
{
    if(argc < 2){
        std::cout << "Missing parameters." << "wpars data.json" << std::endl;
        exit(EXIT_FAILURE);
    }

    /*
    std::shared_ptr<wiki::Properties> ptr_props = std::make_shared<wiki::Properties>();
    if(!ptr_props->load(std::string(argv[1]))){
        exit(EXIT_FAILURE);
    }
    */

    wiki::WiKi wk;

    wk.set_flush_bulk(27);

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

    wk.start();

    exit(EXIT_SUCCESS);
}