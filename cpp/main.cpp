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
        std::cout << "Missing parameters." << std::endl
                  << "wpars data.json [properties.json position_file]"
                  << " [--classes select_classes.csv] [--dates date_properties.csv]"
                  << " [--attrs attribute_properties.csv] [--limit items]" << std::endl
                  << "Exit codes: " << wiki::ExitCode::EXIT_MORE_DATA << " chunk done, more data left; "
                  << wiki::ExitCode::EXIT_ERROR << " error; "
                  << wiki::ExitCode::EXIT_ALL_DONE << " source fully processed" << std::endl;
        exit(wiki::ExitCode::EXIT_ERROR);
    }

    //Optional selection files. They replace the lists built into wiki.h,
    //so the class set can be changed without rebuilding the parser.
    std::string classes_file;
    std::string dates_file;
    std::string attrs_file;

    //Items processed before the parser stops and asks to be started again.
    //Default is 5M per thread, the value the runs so far have used.
    unsigned long items_limit = 5000000UL * wiki::WiKi::max_threads;
    int positional = argc;

    for(int i = 1; i < argc - 1; i++){
        const std::string arg(argv[i]);
        if(arg == "--limit"){
            if(i < positional){
                positional = i;
            }
            items_limit = std::strtoul(argv[++i], nullptr, 10);
        }
        else if(arg == "--classes" || arg == "--dates" || arg == "--attrs"){
            if(i < positional){
                positional = i;  //positional arguments end here
            }

            if(arg == "--classes"){
                classes_file = argv[++i];
            }
            else if(arg == "--dates"){
                dates_file = argv[++i];
            }
            else{
                attrs_file = argv[++i];
            }
        }
    }

    wiki::WiKi wk;

    //the loop counts items per thread, so the limit is divided the same way
    wk.set_bulk_size(std::max(1UL, items_limit / wiki::WiKi::max_threads));
    wk.set_flush_bulk(50000); //100K * MAX_PARSING_THREADS = 600K

    wk.set_save_pos_every(100000);
    wk.set_debug_print(false);

    if(!classes_file.empty() && !wk.load_class_selection(classes_file)){
        std::cout << "Could not load class selection file " << classes_file << std::endl;
        exit(EXIT_FAILURE);
    }

    if(!dates_file.empty() && !wk.load_property_selection(dates_file)){
        std::cout << "Could not load date property file " << dates_file << std::endl;
        exit(EXIT_FAILURE);
    }

    if(!attrs_file.empty() && !wk.load_attribute_selection(attrs_file)){
        std::cout << "Could not load attribute property file " << attrs_file << std::endl;
        exit(EXIT_FAILURE);
    }

    std::cout << "Classes used for selection: " << wk.class_count()
              << " Attribute properties: " << wk.attribute_count()
              << " Items limit: " << items_limit << std::endl;

    if(positional >= 3){
        wk.load_properties(argv[2]);
    }

    if(positional >= 4){
        wk.load_position_file(argv[3]);
    }

    if(!wk.load_source(std::string(argv[1]))){
        std::cout << "Could not load source file" << std::string(argv[1]) << std::endl;
        exit(EXIT_FAILURE);
    }

    //wait untill main thread will finish (TODO: Add signal processor)
    const int result = wk.start();

    std::cout << piutils::get_time_string(false) << " finished. Exit code: " << result
              << (result == wiki::ExitCode::EXIT_ALL_DONE ? " (source fully processed)" :
                  result == wiki::ExitCode::EXIT_MORE_DATA ? " (more data left, start again)" :
                                                             " (error)") << std::endl;
    exit(result);
}
