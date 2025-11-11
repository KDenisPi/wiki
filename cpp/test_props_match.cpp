/**
 * @file test_props_match.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-08
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <string>
#include <memory>

#include "rapidjson/document.h"
#include "smallthings.h"

#include "prop_dict.h"
#include "item_reader.h"
#include "item_parser.h"
#include "receiver_easy.h"

int main (int argc, char* argv[])
{
    int status = EXIT_SUCCESS;
    if(argc < 3){
        std::cout << "Absent necassary data files." << std::endl << "Using: test_props prop_dict.json item.json" << std::endl;
        exit(EXIT_FAILURE);
    }

    std::shared_ptr<char> buffer = std::shared_ptr<char>(new char[MAX_LINE_LENGTH]);// Declare a character array (buffer) to store the line

    std::shared_ptr<wiki::Properties> ptr_props = std::make_shared<wiki::Properties>();
    if(!ptr_props->load(std::string(argv[1]))){
        exit(EXIT_FAILURE);
    }

    std::cout << argv[1] << " Props count: " << ptr_props->MemberCount() << std::endl;
/*
    std::vector<std::string> v_props = {"P31", "P50", "P101", "P136", "P921", "P425", "P569",\
            "P570", "P571", "P577", "P585", "P793", "P921", "P1191", "P2093", "P3150", "P3989", "P4647"\
        "P4647", "P9899", "P10673"};
*/
    std::vector<std::string> v_props = {"P569","P570", "P571", "P575", "P577", "P580", "P582", "P585", "P1619",\
        "P3999", "P6949", "P7124", "P7125", "P10135", "P10673"};


    ptr_props->load_important_property(v_props);

    auto p_found = ptr_props->is_important_property("P571");
    std::cout << " P571 Found: " << p_found << std::endl;

    std::unique_ptr<wiki::ItemReader> ptr_reader = std::make_unique<wiki::ItemReader>();
    if(ptr_reader->init(std::string(argv[2]))){

        auto r_res = ptr_reader->next(buffer.get(), MAX_LINE_LENGTH);
        while(r_res != wiki::ItemReader::END_OF_FILE){
            if(wiki::ItemReader::Res::OK == r_res){
                std::atomic_int sync;
                std::shared_ptr<char> fake_buff;
                std::shared_ptr<wiki::Receiver> receiver = std::make_shared<wiki::ReceiverEasy>();
                std::unique_ptr<wiki::ItemParser> ptr_item = std::make_unique<wiki::ItemParser>(0, &sync, fake_buff, ptr_props, receiver);
                if(ptr_item->load(buffer.get())){
                    auto ptr_item_doc = ptr_item->get();

                    auto itm = ptr_item->parse_item();
                    if(!std::get<0>(itm).empty()){
                        std::cout << " Item ID: " << std::get<0>(itm) << " Label: " << std::get<1>(itm) << " Description: " << std::get<2>(itm) << std::endl;
                    }

                    auto v_claims = ptr_item_doc->FindMember("claims");
                    if(v_claims != ptr_item_doc->MemberEnd()){
                        std::cout << "Name: " << v_claims->name.GetString() << " Type: " << v_claims->value.GetType() << " Count: "
                            << v_claims->value.MemberCount() << std::endl;

                        //Detect "Instance of" property for this Item
                        auto p31 = v_claims->value.FindMember(ptr_item->s_P31.c_str());
                        if( v_claims->value.MemberEnd() != p31){
                            wiki::prop_ids pids;
                            auto insts = ptr_item->get_instance_of(p31, pids);
                            std::cout << "P31 Instance of:";
                            for(auto p31_inst : pids){
                                std::cout << " " << p31_inst;
                            }
                            std::cout << std::endl;
                        }

                        auto ptr_props_doc = ptr_props->get();
                        for(auto cl_v = v_claims->value.MemberBegin(); cl_v != v_claims->value.MemberEnd(); ++cl_v){
                            ptr_item->parse_claim(cl_v);
                        }
                    }
                    else
                        std::cout << "No such member: " << "claims" << std::endl;
                }
                else{
                    std::cout << "No such parse buffer: " << std::endl;
                }
            }
            r_res = ptr_reader->next(buffer.get(), MAX_LINE_LENGTH);
        }

    }
    else{
        std::cout << "Could not init reader for: " << std::string(argv[2]) << std::endl;
    }

    exit(status);
}